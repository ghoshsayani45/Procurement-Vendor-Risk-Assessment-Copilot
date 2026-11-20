"""Append-only audit log (JSONL). Mirrors the audit_events table in app/db/schema.sql until the API writes to Postgres (Week 4).
Path: AUDIT_LOG_PATH (default observability/audit_events.jsonl, git-ignored). Events never contain raw personal data."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.tools.safety import mask_pii


def log_event(event_type: str, **details) -> dict:
    ev = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), event_type=event_type,
              **{k: (mask_pii(v) if isinstance(v, str) else v) for k, v in details.items()})
    path = Path(os.getenv("AUDIT_LOG_PATH", "observability/audit_events.jsonl"))
    if os.getenv("AUDIT_LOG_PATH", "") != "off":
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev
