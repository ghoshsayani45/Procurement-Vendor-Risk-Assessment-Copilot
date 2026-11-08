"""Day 0 step 3: check the course endpoint and record what it supports.

    python -m scripts.check_endpoint            (run from the project root, .venv active)
    python -m scripts.check_endpoint --settings (only show which settings are loaded; no API calls)

Runs, in order: settings loaded -> model list -> plain chat -> JSON mode -> embeddings (if configured).
Each check prints OK or the error with a hint, and the run continues so you see every result at once.
Paste the output (it never prints your API key) into docs/decisions.md or send it to the team.
"""
from __future__ import annotations

import json
import os
import time

from dotenv import load_dotenv

load_dotenv()


def show(name, ok, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}" + (f"  ->  {detail}" if detail else ""))


def hint(e: Exception) -> str:
    s = f"{type(e).__name__}: {e}"
    low = s.lower()
    if "certificate_verify_failed" in low:
        return s[:200] + "\n       hint: set LLM_CA_BUNDLE=certs/<course cert> in .env (see README), and `pip install truststore`"
    if "connect" in low and "timeout" in low or "connecterror" in low or "connection error" in low:
        return s[:200] + "\n       hint: check LLM_BASE_URL, VPN / college network, firewall"
    if "401" in s or "403" in s or "authentication" in low:
        return s[:200] + "\n       hint: API key wrong or not active"
    if "404" in s or "not found" in low:
        return s[:200] + "\n       hint: base URL should usually end with /v1; LLM_MODEL must match an id from the model list exactly"
    if "response_format" in low or "json_object" in low:
        return s[:200] + "\n       hint: set LLM_JSON_MODE=0 in .env"
    if "chat_template_kwargs" in low or "extra_body" in low:
        return s[:200] + "\n       hint: set LLM_DISABLE_THINKING=0 in .env"
    return s[:300]


def main():
    from app import llm_client
    print("Settings")
    for k in ("LLM_BASE_URL", "LLM_MODEL", "EMBED_BASE_URL", "EMBED_MODEL", "LLM_CA_BUNDLE", "LLM_JSON_MODE", "LLM_DISABLE_THINKING",
              "LLM_CONTEXT_TOKENS", "LLM_MAX_OUTPUT_TOKENS", "PROMPT_CONTEXT_WORDS", "PROMPT_MAX_TOKENS", "TEAM_TOKEN_QUOTA"):
        v = os.getenv(k, "")
        print(f"       {k} = {v if v else '(not set)'}")
    print(f"       LLM_API_KEY = {'set (' + str(len(os.getenv('LLM_API_KEY', ''))) + ' chars)' if os.getenv('LLM_API_KEY') else '(not set)'}")
    from pathlib import Path
    env = Path(".env")
    print(f"       .env file used: {env.resolve() if env.exists() else 'NOT FOUND in ' + str(Path.cwd())}")
    if "--settings" in __import__("sys").argv:
        return
    ca = os.getenv("LLM_CA_BUNDLE", "").strip()
    if ca:
        show("CA file exists", os.path.exists(ca), os.path.abspath(ca))
    print()

    try:
        ids = [m.id for m in llm_client._client("LLM_BASE_URL").models.list().data]
        show("Model list", True, ", ".join(ids[:10]))
        if os.getenv("LLM_MODEL", "").strip() not in ids:
            print(f"       WARNING: LLM_MODEL '{os.getenv('LLM_MODEL')}' is not in this list; copy one of the ids above exactly")
    except Exception as e:
        show("Model list", False, hint(e) + "\n       (some servers don't offer /models; continuing)")

    try:
        t0 = time.time()
        out = llm_client.chat([{"role": "user", "content": "Reply with the single word OK."}], tag="check:plain", max_tokens=20)
        u = llm_client.LAST_CALL
        show("Plain chat", "ok" in out.lower(), f"{out[:60]!r} in {time.time() - t0:.1f}s, {u.get('total_tokens')} tokens")
    except Exception as e:
        show("Plain chat", False, hint(e))
        print("\nStopping: fix the plain chat first.")
        return

    try:
        out = llm_client.chat([{"role": "system", "content": "You reply with JSON only."},
                               {"role": "user", "content": 'Return exactly this JSON object: {"ok": true, "n": 3}'}],
                              tag="check:json", json_mode=True, max_tokens=60)
        obj = json.loads(out)
        show("JSON mode" + ("" if os.getenv("LLM_JSON_MODE", "1") == "1" else " (off: parsed from text)"), obj.get("ok") is True, out[:80])
    except json.JSONDecodeError:
        show("JSON mode", False, f"reply was not pure JSON: {out[:120]!r}\n       the harness can still extract JSON from text; note this in the failure log")
    except Exception as e:
        show("JSON mode", False, hint(e))

    if os.getenv("EMBED_MODEL", "").strip() and "REPLACE" not in os.getenv("EMBED_MODEL", ""):
        try:
            v = llm_client.embed(["vendor risk assessment"], tag="check:embed")
            show("Embeddings", True, f"dimension {len(v[0])}  (write this down: it sets the pgvector column size)")
        except Exception as e:
            show("Embeddings", False, hint(e))
    else:
        show("Embeddings", False, "EMBED_MODEL not set; needed only for the dense retrieval baseline")
    print("\nIf plain chat and JSON mode are OK, run:  python -m scripts.prompt_baseline --limit 5")


if __name__ == "__main__":
    main()
