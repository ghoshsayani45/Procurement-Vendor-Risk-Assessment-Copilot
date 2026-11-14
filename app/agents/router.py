"""Router node: decides REFUSE / CLARIFY / RUN before any tool or LLM call (rule-based, so it costs no tokens and cannot be
talked out of a refusal by document text). Implements spec sections 3 and 6.

Mixed requests (spec 6): a FULL_REVIEW or COMPARISON that also asks for an approval or commitment is RUN, and the unsafe part is
declined in the report's gaps. A request that is only an unsafe action is refused.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.tools import register
from app.tools.tools import resolve

R = lambda p: re.compile(p, re.I)
REFUSAL_RULES: list[tuple[str, re.Pattern]] = [
    ("SECRETS", R(r"\bsystem\s+prompt\b|\bapi[\s-]?keys?\b|\bpasswords?\b|\bcredentials?\b|\baccess\s+tokens?\b|\bconnection\s+string\b")),
    ("PII_EXPOSURE", R(r"\b(?:list|show|give|share|reveal|tell|extract|print|send)\b.{0,60}\b(?:employee|staff|caller|customer)s?'?\s+(?:names|details|phone|mobile)"
                       r"|\b(?:list|show|give|share|reveal|tell|extract|print|send)\b.{0,60}\b(?:id\s+numbers|aadhaar|pan\s+numbers?|phone\s+numbers|mobile\s+numbers|home\s+address(?:es)?|personal\s+details)\b")),
    ("SCORE_MANIPULATION", R(r"\b(?:make|ensure|get|have)\b.{0,50}\b(?:come\s+out|rated?|scored?|be)\s+(?:as\s+)?(?:low|lower)(?:[\s-]risk)?\b"
                             r"|\blower\s+(?:the|its|their)\s+(?:score|risk|band|rating)\b|\b(?:leave|keep)\b.{0,40}\bout\s+of\s+the\s+(?:report|assessment)\b"
                             r"|\b(?:omit|hide|remove|drop|suppress|leave\s+out)\b.{0,40}\b(?:findings?|conflict\s+of\s+interest|knockouts?|issues?)\b|\brate\b.{0,30}\blow[\s-]risk\b")),
    ("ACCESS_CONTROL_BYPASS", R(r"\brestricted\b.{0,40}\b(?:docs?|documents?|files?|reports?)\b|\b(?:another|other)\s+team'?s\b|\bbypass\b|\bwithout\s+(?:permission|authori[sz]ation)\b")),
    ("LEGAL_ADVICE", R(r"\benforceable\b|\bcan\s+we\s+sue\b|\bsue\s+(?:them|the\s+vendor|\w+)\b|\blegal\s+advice\b|\blawsuit\b|\bis\s+(?:this|it|the\s+clause)\s+legal\b|\blitigat")),
    ("OUT_OF_SCOPE", R(r"\binvest(?:ing|ment)?\b|\bstock\s+(?:price|tip)|\bshare\s+price\b|\bbuy\s+shares\b|\bcrypto\b|\bweather\b|\brecipe\b|\bpoem\b|\bsearch\s+the\s+web\b|\blatest\s+news\b")),
]
APPROVAL_ACT = R(r"\b(?:approve|sign|countersign|award|execute)\b|\braise\s+(?:a|the)\s+(?:po|purchase\s+order)\b|\bissue\s+(?:a|the)\s+(?:po|purchase\s+order)\b"
                 r"|\bchange\s+(?:the\s+)?payment\s+terms\b|\bcommit\s+to\b|\bon\s+our\s+behalf\b")
IMPERATIVE = R(r"^\s*(?:please\s+|kindly\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|go\s+ahead\s+and\s+|just\s+)?"
               r"(?:approve|sign|countersign|award|execute|raise|issue|change|commit|onboard|mark)\b")
QUESTION_FORM = R(r"^\s*(?:has|have|is|are|was|were|who|what|which|when|does|do|did)\b")
ROUTE_TO = dict(LEGAL_ADVICE="Legal Counsel", ACCESS_CONTROL_BYPASS="Document owner", PII_EXPOSURE="Data Protection Officer",
                SCORE_MANIPULATION="Third-Party Risk Committee")
MESSAGES = dict(
    APPROVAL_OR_COMMITMENT="I can't approve, sign or commit to vendors; only the named approvers can, through the approval panel.",
    LEGAL_ADVICE="I can't give legal opinions; please ask Legal Counsel.",
    ACCESS_CONTROL_BYPASS="I can't show documents outside your access; please ask the document owner.",
    PII_EXPOSURE="I can't repeat personal data found in vendor documents; please contact the Data Protection Officer.",
    SECRETS="I can't share system prompts, keys or other credentials.",
    SCORE_MANIPULATION="I can't change a score or leave findings out; scores come from the rubric and go to the Third-Party Risk Committee.",
    OUT_OF_SCOPE="That is outside vendor risk assessment, so I can't help with it here.",
)


@dataclass
class Route:
    action: str                        # refuse | clarify | run
    request: dict
    template: str | None = None
    vendor_ids: list[str] = field(default_factory=list)
    refusal_category: str | None = None
    clarification: dict | None = None
    declined: list[str] = field(default_factory=list)   # mixed request: unsafe parts declined, rest answered
    notes: list[str] = field(default_factory=list)


def _approvers(vid: str, as_of: str) -> list[str]:
    from app.tools.tools import compliance_checker
    try:
        return compliance_checker(vid, as_of)["required_approvers"]
    except Exception:
        return []


def _clarify(question: str, options: list[str] | None = None) -> dict:
    return dict(behaviour="CLARIFY", question=question[:300], options=(options or [])[:5])


def route(req: dict) -> Route:
    req = dict(req)
    kind = req.get("request_kind", "QUESTION")
    q = (req.get("question") or "").strip()
    as_of = str(req.get("as_of") or "2026-11-01")
    req["as_of"] = as_of

    # ---- vendors
    known = {r["id"] for r in register.directory()}
    vids = [v for v in (req.get("vendor_ids") or []) if v]
    unknown = [v for v in vids if v not in known]
    if not vids and q:
        vids = [r["id"] for r in resolve(q)]

    # ---- refusals (checked first; a refusal never runs tools)
    for cat, rx in REFUSAL_RULES:
        if rx.search(q):
            return Route("refuse", req, refusal_category=cat, vendor_ids=vids)
    approval_ask = bool(APPROVAL_ACT.search(q)) and not QUESTION_FORM.search(q)
    declined = []
    if approval_ask:
        if kind == "QUESTION" or IMPERATIVE.search(q):
            if kind == "QUESTION" or not re.search(r"\b(?:assess|review|evaluate|compare|check|analy[sz]e)\b", q, re.I):
                return Route("refuse", req, refusal_category="APPROVAL_OR_COMMITMENT", vendor_ids=vids)
        declined.append("APPROVAL_OR_COMMITMENT")

    # ---- clarifications (spec 3)
    if unknown:
        return Route("clarify", req, clarification=_clarify(f"I can't find vendor id(s) {', '.join(unknown)}. Which vendor do you mean?"))
    if kind == "FULL_REVIEW":
        if len(vids) != 1:
            if not vids:
                return Route("clarify", req, clarification=_clarify(
                    "I can't find that vendor in the vendor register. Which registered vendor should I assess? Please give the exact name or vendor id."))
            names = [f"{v}: {register.facts(v).legal_name}" for v in vids]
            return Route("clarify", req, clarification=_clarify("Several vendors match. Which one should I assess?", names))
        f = register.facts(vids[0])
        rt = req.get("review_type") or f.review_type.value
        req["review_type"] = rt
        return Route("run", req, "renewal_full" if rt == "RENEWAL" else "new_vendor_full", vids, declined=declined)
    if kind == "COMPARISON":
        if len(vids) < 2:
            return Route("clarify", req, clarification=_clarify("A comparison needs two or three vendors from the same comparison group. Which vendors should I compare?"))
        if len(vids) > 3:
            return Route("clarify", req, clarification=_clarify("I can compare at most three vendors. Which three?", [register.facts(v).legal_name for v in vids][:5]))
        groups = {v: register.facts(v).comparison_group for v in vids}
        if len(set(groups.values())) > 1:
            peers = []
            for v in vids:
                same = [r for r in register.directory() if r["comparison_group"] == groups[v] and r["id"] != v]
                peers += [f"{register.facts(v).legal_name} vs {r['name']}" for r in same]
            desc = "; ".join(f"{register.facts(v).legal_name} ({register.facts(v).category})" for v in vids)
            return Route("clarify", req, clarification=_clarify(
                f"These vendors are not like-for-like ({desc}), so a risk comparison would mislead. Which same-category comparison do you want?", peers))
        return Route("run", req, "comparison", vids, declined=declined)
    return Route("run", req, "single_question", vids[:1], declined=declined)


def refusal_response(rt: Route) -> dict:
    cat = rt.refusal_category
    route_to = ROUTE_TO.get(cat)
    if cat == "APPROVAL_OR_COMMITMENT":
        appr = _approvers(rt.vendor_ids[0], rt.request["as_of"]) if rt.vendor_ids else []
        route_to = ", ".join(appr) if appr else "the approvers named in the approval matrix"
    return dict(behaviour="REFUSE", category=cat, message=MESSAGES[cat], route_to=route_to, audit_event=True)
