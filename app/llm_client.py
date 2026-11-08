"""Single wrapper for every LLM / embeddings call (Day 0, step 2).

All modules call `chat()` / `embed()` here, never the SDK directly, so that:
  * every call's tokens and latency are logged to a ledger (cost per query, Week 4),
  * the team's token quota is never exceeded (hard stop with a safety margin),
  * JSON-mode / schema-validated calls with one repair retry live in one place (Week 3).
"""
from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path
from typing import Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()


class QuotaExceeded(RuntimeError):
    pass


def _verify():
    """TLS trust for the endpoint, without ever disabling verification.
    1. LLM_CA_BUNDLE=path/to/ca.pem   -> trust that CA file (e.g. one issued by the course or institute)
    2. otherwise, if `truststore` is installed (default) -> use the OS certificate store (Windows/macOS), so whatever
       your browser trusts - including antivirus or corporate-proxy root certificates - Python trusts too
    3. otherwise -> the certifi bundle that ships with httpx
    """
    ca = os.getenv("LLM_CA_BUNDLE", "").strip()
    if ca:
        return ca
    if os.getenv("USE_SYSTEM_CERTS", "1") == "1":
        try:
            import ssl
            import truststore
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
    return True


_CLIENTS: dict = {}


def _client(base_url_env: str):
    from openai import OpenAI  # imported lazily so offline scripts don't need the package
    import httpx
    if base_url_env not in _CLIENTS:
        _CLIENTS[base_url_env] = OpenAI(base_url=os.environ[base_url_env].strip(), api_key=os.environ["LLM_API_KEY"].strip(),
                                        http_client=httpx.Client(verify=_verify(), timeout=httpx.Timeout(120.0, connect=20.0)))
    return _CLIENTS[base_url_env]


LEDGER = Path(os.getenv("TOKEN_LEDGER_PATH", "observability/token_ledger.jsonl"))


def tokens_used() -> int:
    if not LEDGER.exists():
        return 0
    return sum(json.loads(l)["total_tokens"] for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip())


def _guard(estimated: int = 0):
    quota = int(os.getenv("TEAM_TOKEN_QUOTA", "0") or 0)
    if quota:
        margin = float(os.getenv("QUOTA_SAFETY_MARGIN", "0.05"))
        if tokens_used() + estimated > quota * (1 - margin):
            raise QuotaExceeded(f"Token quota guard: {tokens_used():,} used of {quota:,}")


def _log(kind: str, model: str, usage, latency_ms: int, tag: str):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(ts=time.time(), kind=kind, model=model, tag=tag, latency_ms=latency_ms,
               prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
               completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
               total_tokens=getattr(usage, "total_tokens", 0) or 0)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


LAST_CALL: dict = {}   # usage record of the most recent chat() call (tokens, latency) for per-query cost accounting


def backend() -> str:
    """LLM_BACKEND=endpoint (default, the course API) or mock (offline, deterministic; for tests and CI)."""
    return os.getenv("LLM_BACKEND", "endpoint")


def chat(messages: list[dict], *, tag: str = "", temperature: float = 0.0, max_tokens: int = 1024,
         json_mode: bool = False, **kw) -> str:
    global LAST_CALL
    if backend() == "mock":
        from app.mock_llm import mock_chat
        t0 = time.time()
        content, usage = mock_chat(messages, temperature=temperature, json_mode=json_mode, tag=tag)
        LAST_CALL = dict(kind="chat", model="mock", tag=tag, latency_ms=int((time.time() - t0) * 1000), **usage)
        return content
    _guard(max_tokens)
    model = os.environ["LLM_MODEL"].strip()
    extra = {}
    if json_mode and os.getenv("LLM_JSON_MODE", "1") == "1":   # set LLM_JSON_MODE=0 if the server rejects response_format
        extra["response_format"] = {"type": "json_object"}
    if _no_thinking(model):                                     # Qwen3: skip the <think> block (vLLM / SGLang chat template flag)
        extra["extra_body"] = {**kw.pop("extra_body", {}), "chat_template_kwargs": {"enable_thinking": False}}
    cap = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "0") or 0)   # e.g. 1024 if the gateway limits answer length
    if cap:
        max_tokens = min(max_tokens, cap)
    t0 = time.time()
    for attempt in (1, 2):
        try:
            r = _client("LLM_BASE_URL").chat.completions.create(model=model, messages=messages, temperature=temperature,
                                                                max_tokens=max_tokens, **extra, **kw)
            break
        except Exception as e:
            status = getattr(e, "status_code", None)
            fitted = _fit_to_window(e) if attempt == 1 else None
            if fitted:                       # the server told us exactly how many prompt tokens it counted: retry once
                max_tokens = fitted
                continue
            if status and 400 <= status < 500:
                raise EndpointRejected(_explain_rejection(e, messages, max_tokens, extra)) from e
            raise
    LAST_CALL = _log("chat", model, r.usage, int((time.time() - t0) * 1000), tag)
    LAST_CALL["finish_reason"] = r.choices[0].finish_reason   # "length" = answer cut off by max_tokens
    return strip_thinking(r.choices[0].message.content or "")


def _fit_to_window(e) -> int | None:
    """If the gateway caps output tokens ('output token limit must be between 1 and N'), return N.
    For vLLM-style 'maximum context length is N ... prompt contains at least M input tokens' errors, return a max_tokens
    that fits (N - M - 16), if at least 200 tokens are left for the answer; otherwise None (the prompt itself is too long)."""
    text = str(getattr(e, "body", None) or e)
    m_cap = re.search(r"output token limit must be between \d+ and (\d+)", text)   # gateway cap on max_tokens
    if m_cap:
        return int(m_cap.group(1))
    m_ctx = re.search(r"maximum context length is (\d+)", text)
    m_in = re.search(r"(?:at least|contains) (\d+) input tokens|(\d+) in the messages", text)
    if not (m_ctx and m_in):
        return None
    left = int(m_ctx.group(1)) - int(next(g for g in m_in.groups() if g)) - 48   # "at least" is a lower bound: keep a margin
    return left if left >= 200 else None


class EndpointRejected(RuntimeError):
    """The server refused the request (HTTP 4xx). The message carries the server's own reason and a likely fix."""


def _explain_rejection(e, messages, max_tokens, extra) -> str:
    body = getattr(e, "body", None)
    if not body:
        try:
            body = e.response.text
        except Exception:
            body = str(e)
    body = json.dumps(body)[:600] if isinstance(body, (dict, list)) else str(body)[:600]
    words = sum(len(str(m.get("content", "")).split()) for m in messages)
    est = int(words * 1.4)
    low = body.lower()
    if "output token limit" in low:
        fix = "The gateway caps answer length: set LLM_MAX_OUTPUT_TOKENS (and PROMPT_MAX_TOKENS) to the limit it states in .env."
    elif any(k in low for k in ("context length", "maximum context", "max_model_len", "too long", "max_tokens", "input tokens", "exceed")):
        fix = (f"PROMPT TOO LONG for the model's context window (this prompt is ~{est:,} tokens + {max_tokens} for the answer). "
               "Lower PROMPT_CONTEXT_WORDS (e.g. 2500) and/or PROMPT_MAX_TOKENS (e.g. 1000) in .env.")
    elif "response_format" in low or "json" in low and "schema" not in low:
        fix = "The server does not accept JSON mode: set LLM_JSON_MODE=0 in .env."
    elif "chat_template_kwargs" in low or "enable_thinking" in low or "extra" in low:
        fix = "The server rejects the Qwen3 thinking switch: set LLM_DISABLE_THINKING=0 in .env."
    elif "model" in low and ("not found" in low or "does not exist" in low):
        fix = "LLM_MODEL does not match a served model id: run python -m scripts.check_endpoint to list them."
    else:
        fix = (f"Unrecognised. Prompt was ~{est:,} tokens with max_tokens={max_tokens}, extras={list(extra)}. "
               "Try PROMPT_CONTEXT_WORDS=2500 first; if that does not help, send this message to the team.")
    return f"HTTP {getattr(e, 'status_code', '?')} from endpoint: {body}\n  -> {fix}"


def _no_thinking(model: str) -> bool:
    """LLM_DISABLE_THINKING=1/0 forces it; default 'auto' = on for Qwen3-family models only."""
    flag = os.getenv("LLM_DISABLE_THINKING", "auto").lower()
    return flag in ("1", "true") or (flag == "auto" and "qwen3" in model.lower())


def strip_thinking(text: str) -> str:
    """Remove reasoning blocks some models emit before the answer (<think>...</think>), even if unterminated."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "<think>" in text:                     # truncated reasoning with no closing tag: keep what follows the last '{'
        text = text[text.rfind("{"):] if "{" in text else ""
    return text.strip()


def chat_structured(messages: list[dict], schema: Type[BaseModel], *, tag: str = "", retries: int = 1, **kw) -> BaseModel:
    """Ask for JSON matching `schema`; on validation failure retry once with the error in the prompt."""
    msgs = list(messages)
    last_err: Optional[str] = None
    for _ in range(retries + 1):
        raw = chat(msgs, tag=tag, json_mode=True, **kw)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            last_err = str(e)[:1500]
            msgs = msgs + [{"role": "assistant", "content": raw},
                           {"role": "user", "content": f"Your JSON did not match the schema. Errors:\n{last_err}\nReturn only corrected JSON."}]
    raise ValueError(f"Structured output failed after {retries + 1} attempts: {last_err}")


def embed(texts: list[str], *, tag: str = "") -> list[list[float]]:
    _guard()
    model = os.environ["EMBED_MODEL"]
    t0 = time.time()
    r = _client("EMBED_BASE_URL").embeddings.create(model=model, input=texts)
    _log("embed", model, r.usage, int((time.time() - t0) * 1000), tag)
    return [d.embedding for d in r.data]
