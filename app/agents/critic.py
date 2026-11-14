"""Critic node: checks the draft response against tool output and the schemas before anything is returned (spec 5 and 9).

Deterministic checks (no LLM, so the check cannot be talked round by the same weak model):
  * schema: the response validates as Report / ComparisonResult / Answer / Clarification / Refusal
  * consistency: tier, score, band, recommendation and approvers equal the compliance_checker output (repaired if not)
  * citations: every finding cites a source; an Answer has at least one citation
  * human decision: never set by the copilot
  * injection: if a scanned document carried an injection, the response must say so
  * personal data: every string is passed through the PII mask
"""
from __future__ import annotations

from pydantic import ValidationError

from app.agents.executor import all_ok, first
from app.schemas import Answer, Clarification, ComparisonResult, Refusal, Report
from app.tools.safety import mask_pii


def _mask(x):
    if isinstance(x, str):
        return mask_pii(x)
    if isinstance(x, list):
        return [_mask(v) for v in x]
    if isinstance(x, dict):
        return {k: _mask(v) for k, v in x.items()}
    return x


def model_for(resp: dict):
    b = resp.get("behaviour")
    if b == "REFUSE":
        return Refusal
    if b == "CLARIFY":
        return Clarification
    if "score" in resp:
        return Report
    if "rows" in resp:
        return ComparisonResult
    return Answer


def review(resp: dict, ex: dict | None) -> tuple[dict, list[str]]:
    notes = []
    masked = _mask(resp)
    if masked != resp:
        notes.append("personal data masked")
    resp = masked
    a = first(ex, "compliance_checker") if ex else None
    if "score" in resp and a:
        s = resp["score"]
        for key, got, want in (("overall", s.get("overall"), a["overall"]), ("band", s.get("band"), a["band"]), ("raw_band", s.get("raw_band"), a["raw_band"])):
            if got != want:
                s[key] = want
                notes.append(f"score.{key} corrected to the engine value")
        if resp.get("tier") != a["tier"]:
            resp["tier"] = a["tier"]
            notes.append("tier corrected")
        if resp.get("recommendation") != a["recommendation"]:
            resp["recommendation"] = a["recommendation"]
            notes.append("recommendation corrected")
        if sorted(resp["approval"].get("required_approvers", [])) != sorted(a["required_approvers"]):
            resp["approval"]["required_approvers"] = a["required_approvers"]
            notes.append("approvers corrected")
        if resp["approval"].get("human_decision") or resp["approval"].get("decided_by"):
            resp["approval"].update(human_decision=None, decided_by=None)
            notes.append("human decision removed (copilot never decides)")
        uncited = [f["code"] for f in resp["findings"] if not f.get("citations")]
        if uncited:
            resp["findings"] = [f for f in resp["findings"] if f.get("citations")]
            notes.append(f"uncited findings dropped: {uncited}")
        engine_codes = {f["code"] for f in a["findings"]}
        invented = [f["code"] for f in resp["findings"] if f["code"] not in engine_codes]
        if invented:
            resp["findings"] = [f for f in resp["findings"] if f["code"] in engine_codes]
            notes.append(f"findings not produced by the engine dropped: {invented}")
    if ex:
        injected = [s["doc_id"] for d in all_ok(ex, "document_search") for s in d.get("scan", []) if s["injection"]]
        if injected:
            blob = " ".join(resp.get("gaps_and_uncertainties", []) + resp.get("caveats", []) + [resp.get("answer", "")])
            if "inject" not in blob.lower():
                msg = f"Prompt-injection attempt ignored in {', '.join(injected)}; treated as data."
                if "gaps_and_uncertainties" in resp:
                    resp["gaps_and_uncertainties"].append(msg)
                elif "caveats" in resp:
                    resp["caveats"].append(msg)
                elif "answer" in resp:
                    resp["answer"] = (resp["answer"] + " " + msg)[:1200]
                notes.append("injection note added")
    model = model_for(resp)
    try:
        return model.model_validate(resp).model_dump(mode="json", exclude_none=False), notes
    except ValidationError as e:
        notes.append(f"schema error: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
        fallback = dict(behaviour="PARTIAL", answer="Partial result: the draft response failed schema validation, so only this notice is returned.",
                        citations=[dict(source_id="tool:critic")])
        return Answer.model_validate(fallback).model_dump(mode="json"), notes
