"""Document store used by the tools: corpus v1 when built (data/processed/corpus_v1.jsonl), otherwise the synthetic and policy
documents in data/synthetic/ (all vendor evidence lives there, so full reviews work offline).

Answer fields in the YAML front matter (planted_issues, adversarial, traps) are removed on load. `not_evidence` stays: it is a property
of the document type (email, press release, web page, chat, draft), which the copilot is allowed to know (spec rule 9).
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.tools.register import ANSWER_FIELDS, ROOT

CORPUS = ROOT / "data" / "processed" / "corpus_v1.jsonl"


def corpus_path() -> Path:
    """CORPUS_PATH in .env (relative to the project root) selects another corpus file, e.g. data/processed/corpus_v1_partial.jsonl
    built from an incomplete raw dataset; default: the frozen corpus v1."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    p = Path((os.getenv("CORPUS_PATH") or "").strip() or CORPUS)
    return p if p.is_absolute() else ROOT / p
SYNTHETIC = ROOT / "data" / "synthetic"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
NON_EVIDENCE_TYPES = {"email", "press_release", "web_page", "chat", "chat_transcript", "draft", "note"}


def _clean(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in ANSWER_FIELDS}


def _from_markdown() -> dict[str, dict]:
    docs = {}
    for p in sorted(SYNTHETIC.rglob("*.md")):
        raw = p.read_text(encoding="utf-8").replace("\r\n", "\n")
        m = _FRONT.match(raw)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        if "doc_id" not in meta:
            continue
        meta = _clean(meta)
        meta.setdefault("slice", p.parent.name)
        meta.setdefault("status", "CURRENT")
        meta["text"] = raw[m.end():]
        docs[meta["doc_id"]] = meta
    return docs


@lru_cache(maxsize=1)
def store() -> dict[str, dict]:
    """doc_id -> {doc_id, vendor_id, title, doc_type, document_date, status, not_evidence, text, ...}."""
    docs = _from_markdown()
    cp = corpus_path()
    if cp.exists():
        with open(cp, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    d = _clean(json.loads(line))
                    docs.setdefault(d["doc_id"], d)
    for d in docs.values():
        d["not_evidence"] = bool(d.get("not_evidence")) or d.get("doc_type") in NON_EVIDENCE_TYPES or d["doc_id"].startswith("ADV-")
    return docs


def source() -> str:
    cp = corpus_path()
    return cp.stem if cp.exists() else "synthetic_only"


def vendor_docs(vendor_id: str) -> list[dict]:
    return [d for d in store().values() if d.get("vendor_id") == vendor_id]


def get(doc_id: str) -> dict | None:
    return store().get(doc_id)
