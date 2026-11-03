"""Offline stand-in for the course LLM (LLM_BACKEND=mock).

Purpose: test the prompting harness, grader and failure classifier end to end without the endpoint or token quota.
It is deliberately a WEAK model with typical small-model habits, so the failure classifier has something to find:
  * treats every checklist item as VERIFIED (missing-as-compliant), always says MEDIUM / PROCEED_WITH_CONDITIONS
  * answers questions by copying the first context sentence that mentions the vendor
  * sometimes emits truncated JSON (exercises the repair-retry path)
  * refuses on obvious keywords only
Its scores mean NOTHING about the real model. Never report mock numbers as a baseline.
"""
from __future__ import annotations

import hashlib
import json
import re


def _h(s: str) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16)


def _field(text, name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def mock_chat(messages, *, temperature=0.0, json_mode=False, tag=""):
    user = messages[-1]["content"]
    allm = "\n".join(m["content"] for m in messages)
    seed = _h(user + tag + str(temperature))
    usage = dict(prompt_tokens=int(len(allm.split()) * 1.3), completion_tokens=0, total_tokens=0)

    if "SUBQUESTIONS" in tag:
        out = json.dumps({"sub_questions": [{"q": "Which vendor and which documents are relevant?", "a": "See context."},
                                            {"q": "What does the policy require?", "a": "See policy excerpt."}]})
        return _done(out, usage)
    if "Your JSON did not match the schema" in user or "was not valid JSON" in user:
        seed = seed | 1  # repaired attempt is always well-formed
    req = next((m["content"] for m in reversed(messages) if m["role"] == "user" and "REQUEST_KIND:" in m["content"]), user)
    kind = _field(req, "REQUEST_KIND") or "QUESTION"
    vendors = [v.strip() for v in _field(req, "VENDOR_IDS").split(",") if v.strip()]
    question = _field(req, "QUESTION").lower()
    docs = re.findall(r"\[DOC (\S+?)\]", req.split("CONTEXT:")[-1])

    if re.search(r"\b(approve|sign|payment terms|system prompt|api key|shares)\b", question) and "if it's fine" not in question:
        cat = "SECRETS" if re.search("prompt|api key", question) else "OUT_OF_SCOPE" if "shares" in question else "APPROVAL_OR_COMMITMENT"
        out = {"behaviour": "REFUSE", "category": cat, "message": "I can't do that; a human approver must.", "route_to": None, "audit_event": True}
    elif kind == "FULL_REVIEW" and vendors:
        cite = [{"source_id": docs[0], "doc_id": docs[0]}] if docs else [{"source_id": "tool:none"}]
        out = {"behaviour": "ANSWER", "vendor_id": vendors[0], "review_type": _field(req, "REVIEW_TYPE") or "NEW_VENDOR", "as_of": "2026-11-01",
               "tier": 1, "summary": "The vendor appears broadly compliant.",
               "findings": [{"code": "CON-PRICE-ESCALATION", "dimension": "contract_terms", "severity": "LOW", "kind": "observation",
                             "statement": "Price escalation noted.", "citations": cite, "needs_legal_review": False}],
               "checklist": [{"item": i, "required": True, "status": "VERIFIED", "evidence_ids": [], "reason": "Provided."}
                             for i in ["SOC2_TYPE2", "ISO27001", "CAIQ", "CYBER_INSURANCE", "FINANCIALS"]],
               "score": {"overall": 18.0, "band": "MEDIUM", "raw_band": "MEDIUM", "dimensions": [], "knockouts": [], "rubric_version": "1.0"},
               "recommendation": "PROCEED_WITH_CONDITIONS", "conditions": [], "approval": {"required_approvers": ["Head of Procurement"]},
               "gaps_and_uncertainties": []}
    elif kind == "COMPARISON" and len(vendors) >= 2:
        out = {"behaviour": "ANSWER", "rows": [{"vendor_id": v, "tier": 1, "overall": 15.0 + i, "band": "MEDIUM", "dimension_points": {}, "key_findings": []}
                                               for i, v in enumerate(vendors)], "caveats": []}
    elif not docs and kind != "QUESTION":
        out = {"behaviour": "CLARIFY", "question": "Which vendor do you mean?", "options": []}
    else:
        ctx = req.split("CONTEXT:")[-1].split("QUESTION:")[0]
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\[DOC \S+?\][^\n]*\n", "", ctx))
        ans = next((s for s in sentences if len(s.split()) > 6), "I could not find this in the documents.")[:600]
        out = {"behaviour": "ANSWER", "answer": ans, "citations": [{"source_id": d, "doc_id": d} for d in docs[:1]] or [{"source_id": "tool:none"}]}
    if "REASONING_FIELD" in allm:
        out = {"reasoning": "Step 1: read the context. Step 2: apply the policy.", **out}
    text = json.dumps(out)
    if seed % 7 == 0:          # ~14%: truncated / malformed JSON
        text = text[: len(text) // 2]
    return _done(text, usage)


def _done(text, usage):
    usage["completion_tokens"] = int(len(text.split()) * 1.3)
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return text, usage
