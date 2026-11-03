"""Single wrapper for every LLM / embeddings call (Day 0, step 2).

All modules call `chat()` / `embed()` here, never the SDK directly, so that:
  * every call's tokens and latency are logged to a ledger (cost per query, Week 4),
  * the team's token quota is never exceeded (hard stop with a safety margin),
  * JSON-mode / schema-validated calls with one repair retry live in one place (Week 3).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()


class QuotaExceeded(RuntimeError):
    pass


def _client(base_url_env: str):
    from openai import OpenAI  # imported lazily so offline scripts don't need the package
    return OpenAI(base_url=os.environ[base_url_env], api_key=os.environ["LLM_API_KEY"])


LEDGER = Path(os.getenv("TOKEN_LEDGER_PATH", "observability/token_ledger.jsonl"))


def tokens_used() -> int:
    if not LEDGER.exists():
        return 0
    return sum(json.loads(l)["total_tokens"] for l in LEDGER.read_text().splitlines() if l.strip())


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
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def chat(messages: list[dict], *, tag: str = "", temperature: float = 0.0, max_tokens: int = 1024,
         json_mode: bool = False, **kw) -> str:
    _guard(max_tokens)
    model = os.environ["LLM_MODEL"]
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    t0 = time.time()
    r = _client("LLM_BASE_URL").chat.completions.create(model=model, messages=messages, temperature=temperature,
                                                        max_tokens=max_tokens, **extra, **kw)
    _log("chat", model, r.usage, int((time.time() - t0) * 1000), tag)
    return r.choices[0].message.content or ""


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
