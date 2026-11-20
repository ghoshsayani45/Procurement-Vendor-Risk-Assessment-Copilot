"""Writer node: turns tool output into the response schemas (Report, ComparisonResult, Answer, PARTIAL fallbacks).

Everything numeric or categorical (tier, checklist, findings, score, band, recommendation, approvers, clause values) is copied from tool
output, never generated (D2). The LLM is used only for (a) an optional plain-language summary of a report and (b) questions that the
structured facts cannot answer, through the Week 2 citation-grounded generator (app.rag.generator).
"""
from __future__ import annotations

import re

from app.agents.executor import all_ok, first
from app.tools import documents
from app.tools.safety import mask_pii
from app.tools.tools import _date_or_none, cite

ITEM_LABEL = dict(SOC2_TYPE2="SOC 2 Type II report", ISO27001="ISO/IEC 27001 certificate", CAIQ="CAIQ security questionnaire",
                  PENTEST="penetration test", CYBER_INSURANCE="cyber insurance", BCP_DR_TEST="BCP/DR test", DPA="data processing agreement (DPA)",
                  FINANCIALS="financial statements", SECURITY_ATTESTATION="security attestation (SOC 2 or ISO 27001)")
ITEM_RX = dict(SOC2_TYPE2=r"\bsoc\s*2\b", ISO27001=r"\biso(?:/iec)?\s*27001\b", CAIQ=r"\bcaiq\b|security\s+questionnaire", PENTEST=r"\bpen(?:etration)?[\s-]?test",
               CYBER_INSURANCE=r"\b(?:cyber\s+)?insurance\b", BCP_DR_TEST=r"\bbcp\b|\bdr\s+test|disaster\s+recovery|business\s+continuity",
               DPA=r"\bdpa\b|data\s+processing\s+agreement", FINANCIALS=r"\bfinancial\s+statements\b|\baudited\s+accounts\b")
CONTROL_RX = {"MFA_NOT_ENFORCED": (r"\bmfa\b|multi[\s-]?factor", "mfa_enforced", "MFA"),
              "UNENCRYPTED_DATA_AT_REST": (r"\bencrypt", "encryption_at_rest", "encryption at rest")}
TOOL_CITE = lambda t: dict(source_id=f"tool:{t}", doc_id=None, title=None, document_date=None, snippet=None)


def _doc_cites(doc_ids) -> list[dict]:
    out, seen = [], set()
    for d in doc_ids:
        if d and d not in seen and documents.get(d):
            seen.add(d)
            out.append(cite(d, {}))
    return out


# ================================================================== shared: safety notes
def safety_gaps(scans: list[dict], vendor_ids: list[str]) -> tuple[list[str], list[dict]]:
    gaps, events = [], []
    for s in scans:
        if s["injection"]:
            gaps.append(f"Prompt-injection attempt ignored: {s['doc_id']} contains instructions aimed at automated reviewers. "
                        "It was treated as data, not followed, and did not change the score.")
            events.append(dict(event_type="INJECTION_DETECTED", doc_id=s["doc_id"], vendor_ids=vendor_ids, excerpt=(s["injection_excerpts"] or [""])[0]))
        if s["not_evidence"]:
            gaps.append(f"Not counted as evidence: {s['doc_id']} ({s['doc_type'] or 'non-evidence document'}); any claim made only there is unverified.")
        if s["pii"]:
            gaps.append(f"Personal data in {s['doc_id']} was not repeated ([REDACTED-PII]).")
    return gaps, events


# ================================================================== FULL_REVIEW -> Report
def _summary(a: dict, fin: dict | None) -> str:
    top = [f["code"] for f in sorted(a["findings"], key=lambda x: -x["points"])][:4]
    ko = f" Knockouts {', '.join(a['knockouts'])} raise the band from {a['raw_band']} to {a['band']}." if a["knockouts"] and a["raw_band"] != a["band"] else \
        (f" Knockouts: {', '.join(a['knockouts'])}." if a["knockouts"] else "")
    s = (f"{a['legal_name']} ({a['review_type'].replace('_', ' ').lower()} review, as of {a['as_of']}): tier {a['tier']}, overall score "
         f"{a['overall']} -> {a['band']}.{ko} Recommendation: {a['recommendation']} (advisory; a named approver decides). "
         f"{len(a['findings'])} finding(s)" + (f", led by {', '.join(top)}." if top else "."))
    return s[:800]


def write_report(rt, ex: dict, llm_summary: bool = False) -> dict:
    a = first(ex, "compliance_checker")
    if a is None:
        return partial_answer("The rubric engine (compliance_checker) did not run, so no score, band or recommendation can be given.", ex)
    fin = first(ex, "financial_risk_calculator")
    scans = [s for d in all_ok(ex, "document_search") for s in d.get("scan", [])]
    gaps, events = safety_gaps(scans, rt.vendor_ids)
    for e in a.get("superseded_evidence", []):
        gaps.append(f"Superseded evidence ignored: {e['doc_id']} (replaced by {e['superseded_by']}); the latest version applies.")
    for d in a["contract"]["pending_amendments"]:
        gaps.append(f"Amendment {d} is not yet in force on {a['as_of']} and was not applied.")
    if "APPROVAL_OR_COMMITMENT" in rt.declined:
        gaps.append(f"Approval declined: the copilot cannot approve vendors; routed to {', '.join(a['required_approvers'])}.")
        events.append(dict(event_type="APPROVAL_DECLINED", vendor_ids=rt.vendor_ids, route_to=a["required_approvers"]))
    if documents.source() == "synthetic_only":
        gaps.append("Document store: synthetic vendor and policy documents only (corpus v1 not built on this machine).")
    findings = [dict(code=f["code"], dimension=f["dimension"], severity=f["severity"], kind="interpretation", statement=mask_pii(f["statement"])[:500],
                     citations=f["citations"], needs_legal_review=f["needs_legal_review"]) for f in a["findings"]]
    checklist = [dict(item=c["item"], required=c["required"], status=c["status"], evidence_ids=c["evidence_ids"], reason=c["reason"][:300]) for c in a["checklist"]]
    score = dict(overall=a["overall"], band=a["band"], raw_band=a["raw_band"], knockouts=a["knockouts"], rubric_version=a["rubric_version"],
                 dimensions=[dict(dimension=d["dimension"], points=d["points"], weight=d["weight"], applicable=d["applicable"], triggered_rules=d["triggered_rules"])
                             for d in a["dimensions"]])
    partial = [f for f in ex["failures"]]
    rep = dict(behaviour="PARTIAL" if partial else "ANSWER", vendor_id=a["vendor_id"], review_type=a["review_type"], as_of=a["as_of"], tier=a["tier"],
               summary=_summary(a, fin), findings=findings, checklist=checklist, score=score, recommendation=a["recommendation"],
               conditions=[mask_pii(c)[:300] for c in a["conditions"]], approval=dict(required_approvers=a["required_approvers"], human_decision=None, decided_by=None),
               gaps_and_uncertainties=gaps + partial, partial_reason="; ".join(partial) or None)
    if llm_summary:
        rep["summary"] = llm_explain(rep, a) or rep["summary"]
    return dict(response=rep, events=events)


def llm_explain(rep: dict, a: dict) -> str | None:
    """Optional plain-language summary by the LLM. The critic rejects it if it introduces numbers or a band not in the tool output."""
    from app import llm_client
    facts = dict(vendor=a["legal_name"], tier=a["tier"], overall=a["overall"], band=a["band"], recommendation=a["recommendation"],
                 knockouts=a["knockouts"], findings=[f["statement"] for f in a["findings"]][:8], approvers=a["required_approvers"])
    msg = [{"role": "system", "content": "You explain a vendor risk assessment to a procurement reviewer in at most 3 sentences. Use only the facts given; "
                                         "do not compute, change or add any score, band or number. Never say the vendor is approved."},
           {"role": "user", "content": f"FACTS: {facts}\nWrite the summary."}]
    try:
        text = llm_client.chat(msg, tag="w3_summary", temperature=0.0, max_tokens=200).strip()
    except Exception:
        return None
    nums = set(re.findall(r"\d+(?:\.\d+)?", text))
    allowed = set(re.findall(r"\d+(?:\.\d+)?", str(facts)))
    if nums - allowed or a["band"] not in text or "approved" in text.lower():
        return None
    return text[:800]


# ================================================================== COMPARISON -> ComparisonResult
def write_comparison(rt, ex: dict) -> dict:
    c = first(ex, "vendor_compare")
    if c is None or not c.get("comparable"):
        return partial_answer("The vendor comparison could not be computed" + (f": {c['reason']}" if c else "."), ex)
    scans = [s for d in all_ok(ex, "document_search") for s in d.get("scan", [])]
    gaps, events = safety_gaps(scans, rt.vendor_ids)
    rows = [dict(vendor_id=r["vendor_id"], tier=r["tier"], overall=r["overall"], band=r["band"], dimension_points=r["dimension_points"],
                 key_findings=r["key_findings"]) for r in c["rows"]]
    names = {r["vendor_id"]: r["legal_name"] for r in c["rows"]}
    caveats = [f"Ranking (lowest risk first, band then score): {' < '.join(names[v] for v in c['ranking'])}.",
               "Scores and bands come from the deterministic rubric engine; recommendations are advisory and need the named approvers."]
    caveats += [f"{r['legal_name']}: knockouts {', '.join(r['knockouts'])} set the band to {r['band']}." for r in c["rows"] if r["knockouts"]]
    if "APPROVAL_OR_COMMITMENT" in rt.declined:
        caveats.append("Approval or award declined: the copilot cannot select or approve a vendor.")
    return dict(response=dict(behaviour="PARTIAL" if ex["failures"] else "ANSWER", rows=rows, caveats=(caveats + gaps + ex["failures"])[:12]), events=events)


# ================================================================== QUESTION -> Answer
def _has(rx, q):
    return re.search(rx, q, re.I) is not None


def structured_answer(q: str, a: dict, scans: list[dict]) -> tuple[list[str], list[str]] | None:
    """Answer from tool facts when the question maps to a known field. Returns (sentences, doc_ids) or None."""
    name = a["legal_name"]
    ck = {c["item"]: c for c in a["checklist"]}
    ct, terms = a["contract"], a["contract"]["terms"]
    cdocs = [ct["doc_id"]] + ct["effective_amendments"]
    non_ev = [s for s in scans if s["not_evidence"]]
    parts, docs = [], []

    # 1. approval status ("has X been approved?") -- the copilot never approves; emails are not evidence
    if _has(r"\b(?:been|already|is|was)\s+(?:\w+\s+){0,2}approved\b|\bapproval\s+status\b", q):
        parts.append(f"No. {name} has no recorded approval: only a named approver can decide through the approval panel, and the copilot never approves vendors.")
        if non_ev:
            parts.append(f"Claims of approval in {', '.join(s['doc_id'] for s in non_ev)} ({', '.join(sorted({s['doc_type'] for s in non_ev}))}) are not evidence and change nothing.")
            docs += [s["doc_id"] for s in non_ev]
        parts.append(f"Current assessment: {a['band']} ({a['overall']}), recommendation {a['recommendation']}; required approvers: {', '.join(a['required_approvers'])}.")
        docs += ["POLICY-DOA-002", a["policy_doc"]]
        return parts, docs

    # 2. missing / outstanding evidence
    if _has(r"\bmissing\b|\bnot\s+(?:yet\s+)?(?:been\s+)?(?:provided|submitted|supplied|given)\b|\boutstanding\b|\bwhich\s+(?:required\s+)?evidence\b|\bwhat\s+evidence\b", q):
        req = [c for c in a["checklist"] if c["required"]]
        by = {}
        for c in req:
            if c["status"] != "VERIFIED":
                by.setdefault(c["status"], []).append(c["item"])
        if not by:
            parts.append(f"{name} has provided all required evidence; every required item is VERIFIED as of {a['as_of']}.")
        for st in ("MISSING", "EXPIRED", "CONTRADICTORY", "EXPIRING_SOON"):
            if st in by:
                parts.append(f"{st}: " + "; ".join(f"{i} ({ITEM_LABEL.get(i, i)})" for i in by[st]) + ".")
        parts.append(f"Required items for tier {a['tier']} are set by {a['policy_doc']}; missing evidence is never treated as compliant.")
        docs += [d for c in req for d in c.get("doc_ids", [])] + [a["policy_doc"]]
        return parts, docs

    # 3. security controls tested by the pentest (MFA, encryption)
    for code, (rx, caiq_key, label) in CONTROL_RX.items():
        if _has(rx, q):
            pen = next((e for e in a["evidence"] if e["type"] == "PENTEST" and e["current"]), None)
            claim = (a.get("caiq") or {}).get(caiq_key)
            if pen and code in pen["findings"]:
                parts.append(f"No: {label} is not enforced. The penetration test {pen['doc_id']} ({pen['issue_date']}) reports {code}"
                             + (f", although the CAIQ claims it is in place, so the CAIQ is CONTRADICTORY." if claim else "."))
                docs.append(pen["doc_id"])
            elif pen:
                parts.append(f"The penetration test {pen['doc_id']} ({pen['issue_date']}) reports no {code} finding; the CAIQ states {label} = {claim}.")
                docs.append(pen["doc_id"])
            else:
                parts.append(f"There is no current penetration test on file, so {label} is unverified; the CAIQ states {label} = {claim}.")
            caiq_doc = f"DOC-{a['vendor_id']}-CAIQ-1"
            docs.append(caiq_doc)
    # 4. evidence items named in the question
    items = [i for i, rx in ITEM_RX.items() if _has(rx, q) and i in ck]
    for i in items:
        c = ck[i]
        st = c["status"] if c["required"] else c["observed_status"]
        verdict = "No" if st not in ("VERIFIED", "EXPIRING_SOON") else "Yes"
        parts.append(f"{verdict}: {i} ({ITEM_LABEL[i]}) status is {st} as of {a['as_of']} - {c['reason']}.")
        docs += c.get("doc_ids", [])
        if st not in ("VERIFIED", "EXPIRING_SOON"):
            caiq = f"DOC-{a['vendor_id']}-CAIQ-1"
            docs += [caiq, a["policy_doc"]]          # what the vendor declared + the rule that requires the item
        if st not in ("VERIFIED", "EXPIRING_SOON") and non_ev:
            parts.append(f"Statements in {', '.join(s['doc_id'] for s in non_ev)} are not evidence (spec rule 9), so {i} cannot be marked verified on them.")
            docs += [s["doc_id"] for s in non_ev]
    # 5. contract clauses (effective terms: amendments in force on as_of applied)
    amend = f" (as amended by {', '.join(ct['effective_amendments'])})" if ct["effective_amendments"] else ""
    pend = f" Amendment(s) {', '.join(ct['pending_amendments'])} are not yet in force and were not applied." if ct["pending_amendments"] else ""
    clause = []
    if _has(r"\bnotice\b|auto[\s-]?renew", q):
        clause.append(f"the contract auto-renews unless cancelled {terms['renewal_notice_days']} days before the term ends (policy maximum 90 days)"
                      if terms["auto_renewal"] else f"the contract does not auto-renew; the renewal notice period is {terms['renewal_notice_days']} days")
    if _has(r"\bliabilit", q):
        cap = terms["vendor_liability_cap_months_fees"]
        clause.append((f"the vendor's liability cap is {cap} months' fees (policy minimum 12)" if cap is not None else "the vendor's liability is uncapped")
                      + ("; the customer's liability is capped" if terms["customer_liability_capped"] else "; the customer's liability is uncapped"))
    if _has(r"\bbreach\b|\bnotify\b|\bnotification\b", q):
        h = terms["breach_notification_hours"]
        clause.append(f"the vendor must notify a personal-data breach within {h} hours (policy maximum 48)" if h is not None else "the contract has no breach-notification clause")
    if _has(r"\bstore\b|\bstored\b|\blocation\b|\bresiden|cross[\s-]?border|\boffshore\b|\bwhere\b.{0,30}\bdata\b", q):
        clause.append(f"personal data is stored in {terms['data_location']}"
                      + ("" if terms["data_location"] == "India" else ("; contractual cross-border safeguards are in place" if terms["cross_border_safeguards"]
                                                                       else "; there are no contractual cross-border safeguards")))
    if _has(r"\bterminat", q):
        clause.append("the customer may terminate for convenience" if terms["termination_for_convenience"] else "there is no right to terminate for convenience")
    if _has(r"\baudit\s+rights?\b|\bright\s+to\s+audit\b", q):
        clause.append("the customer has audit rights" if terms["audit_rights"] else "the customer has no audit rights")
    if _has(r"\bprice\b|\bescalat", q):
        clause.append(f"annual price escalation is {terms['annual_price_escalation_pct']}% (policy maximum 8%)")
    if _has(r"sub[\s-]?processor", q):
        clause.append("new sub-processors need the customer's prior approval" if terms["subprocessor_approval"] else "the customer has no approval right over sub-processors")
    if _has(r"governing\s+law", q):
        clause.append(f"governing law is {terms['governing_law']}")
    if clause:
        parts.append(f"Under {name}'s current contract{amend}, " + "; ".join(clause) + "." + pend)
        docs += cdocs
    # 6. performance (renewals)
    p = a.get("performance")
    if p and _has(r"\bp1\b|\bincidents?\b|\bsla\b|\buptime\b|late\s+deliver|\bdisputes?\b", q):
        parts.append(f"In the last 12 months ({p['period']}) {name} had {p['p1_incidents_12m']} P1 incident(s), SLA attainment {p['sla_attainment_pct']}% "
                     f"against a {p['sla_target_pct']}% target, {p['late_delivery_pct']}% late deliveries and {p['open_disputes']} open dispute(s).")
        docs += [a.get("performance_doc"), f"DOC-{a['vendor_id']}-INCIDENTS-1"]
    # 7. score / tier / band
    if _has(r"\btier\b|\bband\b|\brisk\s+(?:rating|level|score|band)\b|\boverall\s+score\b|\brecommend", q) and not parts:
        parts.append(f"{name} is tier {a['tier']}; overall score {a['overall']} -> {a['band']}"
                     + (f" (knockouts: {', '.join(a['knockouts'])})" if a["knockouts"] else "") + f"; recommendation {a['recommendation']} (advisory).")
        docs.append(a["policy_doc"])
    return (parts, docs) if parts else None


def _extractive(q: str, hits: list[dict]) -> tuple[str, list[str]]:
    """No-LLM fallback: the 1-2 sentences of the top passages that share the most words with the question."""
    qt = {w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 3}
    best = []
    from app.tools.safety import INJECTION_RE
    usable = [h for h in hits if not h.get("injection") and not h.get("not_evidence")]
    for h in usable[:4]:
        body = h["text"].split("\n", 1)[-1]
        for s in re.split(r"(?<=[.!?])\s+|\n+", body):
            st = set(re.findall(r"[a-z0-9]+", s.lower()))
            if len(s.split()) >= 5 and not INJECTION_RE.search(s):
                rank = usable.index(h)                     # prefer higher-ranked passages: 1.0, 0.85, 0.7, 0.55
                best.append((len(qt & st) * (1 - 0.15 * rank), -rank, s.strip(" |#*"), h["doc_id"]))
    best.sort(reverse=True)
    picks = best[:2]
    return " ".join(p[2] for p in picks), list(dict.fromkeys(p[3] for p in picks))


_AMOUNT = re.compile(r"(?:inr|rs\.?|₹)\s*([\d][\d,]*(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?)\b", re.I)
_UNIT = {"cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000}


def policy_approvers_answer(q: str) -> tuple[list[str], list[str]] | None:
    """'Who approves an INR 3 crore renewal rated MEDIUM with a contract finding?' -> computed from the rubric's approval matrix and
    additional approvers, exactly as full reviews do (D2), instead of asking the 8B model to apply the rules (live runs 2026-11-20:
    the model dropped Legal Counsel in 2 of 3 runs). Only for questions that name an amount and ask who approves."""
    if not re.search(r"\bwho\b.{0,40}\bapprov|\bapprov\w*\b.{0,30}\b(?:needed|required|whom)\b|\bwhich approvers\b", q, re.I):
        return None
    m = _AMOUNT.search(q)
    if not m:
        return None
    from app.scoring.engine import load_rubric
    r = load_rubric()
    value = float(m.group(1).replace(",", "")) * _UNIT[m.group(2).lower()]
    row = next(x for x in r["approval_matrix"] if x["max_inr"] is None or value <= x["max_inr"])
    approvers, why = list(row["approvers"]), []
    limit = f"up to INR {row['max_inr']:,}" if row["max_inr"] else "above INR 5 crore"
    add = r["additional_approvers"]
    band = next((b for b in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if re.search(rf"\b{b}\b", q, re.I)), None)
    rules = [(band in ("HIGH", "CRITICAL"), add["band_high_or_critical"], f"band {band}"),
             (re.search(r"\bcontract(?:ual)?\s+(?:finding|issue|term)", q, re.I), add["any_contract_terms_finding"], "a contract finding"),
             (re.search(r"\bdata[\s-]protection\s+(?:finding|issue)|\bpersonal[\s-]data\s+(?:finding|issue)|\bDPA\b", q, re.I),
              add["any_data_protection_finding"], "a data-protection finding"),
             (re.search(r"\bconflict\s+of\s+interest\b", q, re.I), add["conflict_of_interest"], "a conflict of interest")]
    for hit, who, reason in rules:
        if hit and who not in approvers:
            approvers.append(who)
            why.append(f"{who} because of {reason}")
    parts = [f"Required approvers: {', '.join(approvers)}.",
             f"The annual value (INR {value:,.0f}) falls in the approval band {limit}: {', '.join(row['approvers'])}."
             + (f" Added: {'; '.join(why)}." if why else "")
             + (f" Band {band} adds no approver on its own." if band in ("LOW", "MEDIUM") else ""),
             "The copilot only routes the decision; a named approver decides in the approval panel."]
    return parts, ["POLICY-DOA-002"]


def _clean_dates(cites: list[dict]) -> list[dict]:
    """Citation dates must be plain dates: some sources store a time of day or a version label (2026-11-20)."""
    for c in cites:
        if "document_date" in c:
            c["document_date"] = _date_or_none(c.get("document_date"))
    return cites


def write_answer(rt, ex: dict, llm: str = "none") -> dict:
    q = rt.request.get("question") or ""
    a = first(ex, "compliance_checker")
    ds = first(ex, "document_search") or {}
    scans = ds.get("scan", [])
    gaps, events = safety_gaps(scans, rt.vendor_ids)
    sa = structured_answer(q, a, scans) if a else None
    pa = None if (a or sa) else policy_approvers_answer(q)
    if sa:
        parts, docs = sa
        cites = _doc_cites(docs) + [TOOL_CITE("compliance_checker")]
        text = " ".join(parts)
    elif pa:
        parts, docs = pa
        cites = _doc_cites(docs) + [TOOL_CITE("rubric_engine")]
        text = " ".join(parts)
    elif llm in ("endpoint", "mock") and ds.get("hits"):
        try:
            text, cites = _rag_answer(q, ds, rt.request["as_of"], llm)
        except Exception as e:  # a model or network failure must never crash a request
            text, docs = _extractive(q, ds["hits"])
            text = (f"From {', '.join(docs)}: " + text) if text else ""
            cites = _doc_cites(docs)
            gaps.append(f"The model's answer could not be used ({type(e).__name__}); this answer quotes the retrieved passages instead.")
            events.append(dict(event_type="LLM_ANSWER_FAILED", error=f"{type(e).__name__}: {str(e)[:200]}"))
    elif ds.get("hits"):
        text, docs = _extractive(q, ds["hits"])
        text = (f"From {', '.join(docs)}: " + text) if text else ""
        cites = _doc_cites(docs)
    else:
        text, cites = "", []
    if not text or not cites:
        return partial_answer("No passage or structured record answers this question.", ex)
    for h in ds.get("hits", []):
        if h.get("injection") and not any(h["doc_id"] in g for g in gaps):
            gaps.append(f"Prompt-injection attempt ignored: retrieved passage {h['doc_id']} contains instructions aimed at automated reviewers; it was not used.")
            events.append(dict(event_type="INJECTION_DETECTED", doc_id=h["doc_id"], vendor_ids=rt.vendor_ids, excerpt=""))
    notes = [g for g in gaps if g.startswith(("Prompt-injection", "The model's answer could not be used"))]
    if notes:
        text += " Note: " + " ".join(notes)
    beh = "PARTIAL" if ex["failures"] else "ANSWER"
    return dict(response=dict(behaviour=beh, answer=mask_pii(text)[:1200], citations=_clean_dates(cites[:8])), events=events)


def _rag_answer(q: str, ds: dict, as_of: str, llm: str) -> tuple[str, list[dict]]:
    import os
    from app.rag.generator import generate
    from app.rag.index import Hit
    from app.tools.tools import _pipeline
    if llm == "mock":
        os.environ["LLM_BACKEND"] = "mock"
    pipe, _ = _pipeline()
    by_id = {c.chunk_id: c for c in pipe.index.chunks}
    hits = [Hit(by_id[h["chunk_id"]], h["score"], "copilot") for h in ds["hits"] if h["chunk_id"] in by_id]
    ans = generate(q, hits, as_of=as_of, tag="w3_answer")
    d = ans.to_answer_dict()
    cites = [c for c in d["citations"] if c.get("source_id") != "none"]
    for c in cites:                                   # Citation.source_id is the chunk id; keep doc_id for grading
        c.setdefault("doc_id", c["source_id"].split("#")[0])
    return d["answer"], cites


def partial_answer(reason: str, ex: dict) -> dict:
    tools = [r["tool"] for r in ex["results"]] or ["copilot"]
    return dict(response=dict(behaviour="PARTIAL", answer=f"Partial result: {reason} " + " ".join(ex["failures"]),
                              citations=[TOOL_CITE(tools[0])]), events=[dict(event_type="PARTIAL_RESULT", reason=reason)])
