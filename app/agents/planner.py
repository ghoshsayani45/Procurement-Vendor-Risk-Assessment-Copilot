"""Planner node: deterministic plan templates (spec section 3). Templates, not LLM planning: the step-1.6 baseline showed the 8B model
choosing shapes by topic; a fixed plan per request kind removes that failure and keeps every run within the 6-step plan limit."""
from __future__ import annotations

from app.schemas import Plan
from app.tools import register


def make_plan(template: str, req: dict, vids: list[str]) -> Plan:
    as_of = req["as_of"]
    steps = []

    def add(tool, purpose, **args):
        steps.append(dict(step=len(steps) + 1, tool=tool, arguments=args, purpose=purpose))

    if template in ("new_vendor_full", "renewal_full"):
        v = vids[0]
        name = register.facts(v).legal_name
        add("vendor_search", "Confirm the vendor and list its documents", vendor_id=v)
        add("compliance_checker", "Checklist, findings, score, band, recommendation and approvers from the rubric engine",
            vendor_id=v, as_of=as_of, review_type=req.get("review_type"))
        add("financial_risk_calculator", "Financial ratios against policy thresholds", vendor_id=v, as_of=as_of)
        add("document_search", "Retrieve contract and evidence passages; scan the vendor's documents for injections and non-evidence claims",
            query=f"{name} contract terms liability renewal notice breach notification certificates", vendor_id=v, scan_vendor_documents=True)
    elif template == "comparison":
        add("vendor_compare", "Score each vendor with the rubric engine and rank them", vendor_ids=vids, as_of=as_of)
        for v in vids:
            add("document_search", "Scan the vendor's documents for injections and non-evidence claims",
                query=f"{register.facts(v).legal_name} risk evidence", vendor_id=v, scan_vendor_documents=True, k=3)
    else:
        q = req.get("question") or ""
        if vids:
            add("vendor_search", "Confirm the vendor and list its documents", vendor_id=vids[0])
            add("compliance_checker", "Structured facts: evidence status, contract terms, performance, score",
                vendor_id=vids[0], as_of=as_of, review_type=req.get("review_type"))
        add("document_search", "Retrieve passages that answer the question", query=q, vendor_id=vids[0] if vids else None,
            scan_vendor_documents=bool(vids))
    return Plan(review_template=template, steps=steps)
