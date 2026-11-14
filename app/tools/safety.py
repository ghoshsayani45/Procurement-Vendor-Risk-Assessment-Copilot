"""Untrusted-document checks shared by the tools and the critic (spec rules 7-9, decision D21/D25).

scan(doc)  -> flags for one document:
  injection     instruction-like text aimed at an AI / automated reviewer (HTML comments and hidden text are read too)
  not_evidence  the document type cannot count as evidence (email, press release, web page, chat, draft)
  pii           personal data present (it must be masked, never repeated)
Patterns target the *addressee* ("AI assistant", "automated ... tools", "system note") or the *imperative* ("disregard prior
instructions", "print your system prompt"), so ordinary policy wording such as "superseded certificates are disregarded" is not flagged.
"""
from __future__ import annotations

import re

from app.rag.generator import PII_RES, mask_pii   # one PII definition for the whole copilot

INJECTION_PATTERNS = [
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|rules|guidance)",
    r"\binstructions?\s+to\s+(?:any\s+)?(?:automated|AI)\b",
    r"\bsystem\s+note\s+for\s+(?:AI|automated)",
    r"\b(?:to\s+any\s+|dear\s+)?AI\s+(?:assistant|reviewer|model)s?\s+(?:reading|processing|reviewing)\b",
    r"^\s*\W*\s*assistant\s*:",                                     # "[hidden text] Assistant: when summarising..."
    r"\b(?:print|reveal|show|output)\s+(?:your|the)\s+(?:full\s+)?(?:system\s+prompt|api\s+key)",
    r"\btreat\s+every\s+clause\b",
    r"\bomit\s+(?:it|this|them)\s+from\s+(?:any|the)\s+findings",
    r"\bdo\s+not\s+(?:mention|cite|report)\s+this\s+(?:note|page|document|instruction)",
    r"\b(?:state|say|report)\s+that\s+it\s+is\s+low\s+risk",
    r"\bapprove\s+the\s+renewal\s+automatically",
]
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.I | re.M)


def injection_spans(text: str, width: int = 90) -> list[str]:
    """Short, PII-masked excerpts around each match (for the audit log; never shown as an instruction)."""
    out = []
    for m in INJECTION_RE.finditer(text or ""):
        a, b = max(0, m.start() - 20), min(len(text), m.end() + width)
        out.append(mask_pii(re.sub(r"\s+", " ", text[a:b]).strip()))
    return out[:3]


def has_pii(text: str) -> bool:
    return any(rx.search(text or "") for rx, _ in PII_RES)


def scan(doc: dict) -> dict:
    text = doc.get("text", "")
    spans = injection_spans(text)
    return dict(doc_id=doc["doc_id"], title=doc.get("title", ""), doc_type=doc.get("doc_type", ""),
                injection=bool(spans), injection_excerpts=spans, not_evidence=bool(doc.get("not_evidence")), pii=has_pii(text))
