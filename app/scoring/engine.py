"""Deterministic vendor risk scoring engine (rubric v1.0).

Used three ways:
  * to compute ground truth for the 35 synthetic vendors (Week 1, step 1.3),
  * as the compliance_checker / financial_risk_calculator tools (Week 2),
  * as the reference the LLM's report is graded against (Weeks 3-4).

No LLM, no randomness: assess(facts) is a pure function of the facts, the rubric and as_of.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml

from app.schemas import (ChecklistStatus as CS, ContractTerms, DataAccess, EvidenceItem, EvidenceType as ET,
                         ReviewType, VendorFacts)

RUBRIC_PATH = Path(__file__).with_name("rubric.yaml")
PERSONAL = {DataAccess.PERSONAL, DataAccess.SENSITIVE_PERSONAL}
BAND_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
VALID = {CS.VERIFIED, CS.EXPIRING_SOON}


def load_rubric(path: Path = RUBRIC_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def _severity(points: int) -> str:
    return "HIGH" if points >= 30 else "MEDIUM" if points >= 15 else "LOW"


class _Collector:
    def __init__(self):
        self.findings: list[dict] = []

    def add(self, code, dimension, points, statement, refs, legal=False):
        self.findings.append(dict(code=code, dimension=dimension, points=points,
                                  severity="CRITICAL" if dimension == "governance" else _severity(points),
                                  statement=statement, evidence_refs=[r for r in refs if r], needs_legal_review=legal))


# ------------------------------------------------------------------ helpers
def tier_of(f: VendorFacts, r: dict) -> int:
    t1, t2 = r["tiering"]["tier_1"], r["tiering"]["tier_2"]
    if f.data_access.value in t1["data_access_in"] or f.business_critical or f.annual_value_inr >= t1["annual_value_inr_gte"]:
        return 1
    if f.data_access.value in t2["data_access_in"] or f.annual_value_inr >= t2["annual_value_inr_gte"]:
        return 2
    return 3


def effective_contract(c: ContractTerms, as_of: date) -> ContractTerms:
    """Base terms with amendments effective on or before as_of applied in date order."""
    eff = deepcopy(c)
    for a in sorted(c.amendments, key=lambda a: a.effective_date):
        if a.effective_date <= as_of:
            for k, v in a.changes.items():
                setattr(eff, k, v)
    return eff


def current_evidence(f: VendorFacts, etype: ET) -> Optional[EvidenceItem]:
    """Latest non-superseded evidence of a type (version traps resolve here)."""
    items = [e for e in f.evidence if e.type == etype and not e.superseded_by]
    if not items:
        return None
    key = lambda e: e.expiry_date or e.period_end or e.issue_date or date.min
    return max(items, key=key)


def _validity(valid_until: date, as_of: date, soon: int) -> CS:
    if as_of > valid_until:
        return CS.EXPIRED
    if (valid_until - as_of).days <= soon:
        return CS.EXPIRING_SOON
    return CS.VERIFIED


def evidence_status(f: VendorFacts, etype: ET, r: dict, as_of: date) -> tuple[CS, Optional[EvidenceItem], str, Optional[date]]:
    rules, soon = r["evidence_rules"], r["expiring_soon_days"]
    e = current_evidence(f, etype)
    if etype == ET.CAIQ:
        if not f.caiq or not f.caiq.completed_date:
            return CS.MISSING, None, "No completed CAIQ on file", None
        vu = f.caiq.completed_date + timedelta(days=rules["CAIQ"]["max_age_days"])
        return _validity(vu, as_of, soon), e, f"Completed {f.caiq.completed_date}; valid to {vu}", vu
    if e is None:
        return CS.MISSING, None, f"No {etype.value} evidence on file", None
    if etype == ET.SOC2_TYPE2:
        vu = e.period_end + timedelta(days=rules["SOC2_TYPE2"]["max_age_days_from_period_end"])
        return _validity(vu, as_of, soon), e, f"Report period ends {e.period_end}; current to {vu}", vu
    if etype in (ET.ISO27001, ET.CYBER_INSURANCE):
        return _validity(e.expiry_date, as_of, soon), e, f"Expires {e.expiry_date}", e.expiry_date
    if etype in (ET.PENTEST, ET.BCP_DR_TEST):
        vu = e.issue_date + timedelta(days=rules[etype.value]["max_age_days"])
        return _validity(vu, as_of, soon), e, f"Dated {e.issue_date}; current to {vu}", vu
    raise ValueError(etype)


def contradictions(f: VendorFacts, statuses: dict, contract: ContractTerms) -> list[str]:
    if not f.caiq:
        return []
    c, out = f.caiq, []
    pen = current_evidence(f, ET.PENTEST)
    pf = set(pen.findings) if pen else set()
    if c.iso27001_certified and statuses.get(ET.ISO27001) not in VALID:
        out.append(f"CAIQ claims current ISO 27001 certification, but the certificate on file is {statuses.get(ET.ISO27001).value}")
    if c.soc2_type2 and statuses.get(ET.SOC2_TYPE2) not in VALID:
        out.append(f"CAIQ claims a current SOC 2 Type II report, but the report on file is {statuses.get(ET.SOC2_TYPE2).value}")
    if c.data_residency != contract.data_location:
        out.append(f"CAIQ states data residency '{c.data_residency}', but the contract places data in '{contract.data_location}'")
    if c.encryption_at_rest and "UNENCRYPTED_DATA_AT_REST" in pf:
        out.append("CAIQ claims encryption at rest, but the penetration test found unencrypted data at rest")
    if c.mfa_enforced and "MFA_NOT_ENFORCED" in pf:
        out.append("CAIQ claims MFA is enforced, but the penetration test found MFA not enforced")
    return out


def band_of(score: float, r: dict) -> str:
    band = "LOW"
    for b in r["bands"]:
        if score >= b["min"]:
            band = b["band"]
    return band


# ------------------------------------------------------------------ main
def assess(f: VendorFacts, r: Optional[dict] = None, as_of: Optional[date] = None) -> dict:
    r = r or load_rubric()
    as_of = as_of or date.fromisoformat(r["review_as_of"])
    P, L = r["points"], r["limits"]
    tier = tier_of(f, r)
    personal = f.data_access in PERSONAL
    contract = effective_contract(f.contract, as_of)
    col = _Collector()

    # ---- checklist
    required = [ET(x) for x in r["required_evidence"][tier]]
    statuses, details = {}, {}
    for et in [ET.SOC2_TYPE2, ET.ISO27001, ET.CAIQ, ET.PENTEST, ET.CYBER_INSURANCE, ET.BCP_DR_TEST]:
        statuses[et], ev, why, vu = evidence_status(f, et, r, as_of)
        details[et] = (ev, why, vu)
    contra = contradictions(f, statuses, contract)
    if contra:
        statuses[ET.CAIQ] = CS.CONTRADICTORY

    checklist = []

    def ck(item, req, status, ids, reason):
        checklist.append(dict(item=item.value, required=req, status=(status if req else CS.NOT_REQUIRED).value,
                              observed_status=status.value, evidence_ids=[i for i in ids if i], reason=reason))

    for et in [ET.SOC2_TYPE2, ET.ISO27001, ET.CAIQ, ET.PENTEST, ET.CYBER_INSURANCE, ET.BCP_DR_TEST]:
        ev, why, _ = details[et]
        reason = why if et != ET.CAIQ or not contra else "; ".join(contra)
        ck(et, et in required, statuses[et], [ev.evidence_id if ev else None], reason)
    if ET.SECURITY_ATTESTATION in required:
        best = CS.VERIFIED if CS.VERIFIED in (statuses[ET.SOC2_TYPE2], statuses[ET.ISO27001]) else \
            CS.EXPIRING_SOON if CS.EXPIRING_SOON in (statuses[ET.SOC2_TYPE2], statuses[ET.ISO27001]) else \
            CS.EXPIRED if CS.EXPIRED in (statuses[ET.SOC2_TYPE2], statuses[ET.ISO27001]) else CS.MISSING
        statuses[ET.SECURITY_ATTESTATION] = best
        ids = [details[x][0].evidence_id for x in (ET.SOC2_TYPE2, ET.ISO27001) if details[x][0]]
        ck(ET.SECURITY_ATTESTATION, True, best, ids, f"Best of SOC 2 ({statuses[ET.SOC2_TYPE2].value}) and ISO 27001 ({statuses[ET.ISO27001].value})")
    dpa_ev = current_evidence(f, ET.DPA)
    dpa_status = CS.VERIFIED if contract.dpa_signed else CS.MISSING
    ck(ET.DPA, personal and ET.DPA in required, dpa_status, [dpa_ev.evidence_id if dpa_ev else None],
       "Signed DPA on file" if contract.dpa_signed else "No signed data processing agreement")
    min_years = r["evidence_rules"]["FINANCIALS"]["min_years_by_tier"][tier]
    fin_status = CS.VERIFIED if len(f.financials) >= min_years else CS.MISSING
    ck(ET.FINANCIALS, True, fin_status, [fy.doc_id for fy in f.financials],
       f"{len(f.financials)} of {min_years} required year(s) of financial statements")
    statuses[ET.DPA], statuses[ET.FINANCIALS] = dpa_status, fin_status

    # ---- security & compliance
    S = P["security_compliance"]
    sec_items = [et for et in required if et in (ET.SOC2_TYPE2, ET.ISO27001, ET.SECURITY_ATTESTATION, ET.CAIQ,
                                                 ET.PENTEST, ET.CYBER_INSURANCE, ET.BCP_DR_TEST)]
    for et in sec_items:
        st = statuses[et]
        if et == ET.SECURITY_ATTESTATION:
            refs = [details[x][0].evidence_id for x in (ET.SOC2_TYPE2, ET.ISO27001) if details[x][0]]
        else:
            refs = [details[et][0].evidence_id if details[et][0] else None]
        label = et.value
        if st == CS.MISSING:
            col.add(f"SEC-{label}-MISSING", "security_compliance", S["evidence_missing"], f"Required {label} evidence is missing", refs)
        elif st == CS.EXPIRED:
            col.add(f"SEC-{label}-EXPIRED", "security_compliance", S["evidence_expired"], f"{label} has expired ({details.get(et, (None, ''))[1]})", refs)
        elif st == CS.EXPIRING_SOON:
            col.add(f"SEC-{label}-EXPIRING", "security_compliance", S["evidence_expiring_soon"], f"{label} expires within {r['expiring_soon_days']} days ({details.get(et, (None, ''))[1]})", refs)
        elif st == CS.CONTRADICTORY:
            col.add("SEC-CAIQ-CONTRADICTION", "security_compliance", S["evidence_contradictory"], "; ".join(contra), refs)
    pen = details[ET.PENTEST][0]
    if ET.PENTEST in required and pen and pen.open_critical_findings > 0:
        col.add("SEC-PENTEST-CRITICAL-OPEN", "security_compliance", S["pentest_open_critical"],
                f"Penetration test has {pen.open_critical_findings} open critical finding(s)", [pen.evidence_id])
    ins = details[ET.CYBER_INSURANCE][0]
    min_cov = r["evidence_rules"]["CYBER_INSURANCE"]["min_coverage_inr_by_tier"][tier]
    if ins and (ins.coverage_inr or 0) < min_cov:
        col.add("SEC-INSURANCE-LOW", "security_compliance", S["insurance_below_minimum"],
                f"Cyber insurance cover INR {ins.coverage_inr:,} is below the tier {tier} minimum of INR {min_cov:,}", [ins.evidence_id])

    # ---- data protection
    D = P["data_protection"]
    cdoc = contract.doc_id
    amend_refs = [a.amendment_id for a in f.contract.amendments if a.effective_date <= as_of]
    if personal:
        if not contract.dpa_signed:
            col.add("DP-NO-DPA", "data_protection", D["no_signed_dpa"], "Vendor will process personal data but no DPA is signed", [cdoc], True)
        if contract.breach_notification_hours is None:
            col.add("DP-BREACH-NOTICE-ABSENT", "data_protection", D["breach_notice_absent"], "Contract has no personal-data breach notification clause", [cdoc], True)
        elif contract.breach_notification_hours > L["breach_notice_max_hours"]:
            col.add("DP-BREACH-NOTICE-LONG", "data_protection", D["breach_notice_over_limit"],
                    f"Breach notification window is {contract.breach_notification_hours} hours; policy maximum is {L['breach_notice_max_hours']}", [cdoc], True)
        if contract.data_location != "India" and not contract.cross_border_safeguards:
            col.add("DP-OFFSHORE-NO-SAFEGUARD", "data_protection", D["offshore_without_safeguards"],
                    f"Personal data stored in {contract.data_location} without contractual cross-border safeguards", [cdoc], True)
        if not contract.subprocessor_approval:
            col.add("DP-NO-SUBPROCESSOR-CONTROL", "data_protection", D["no_subprocessor_approval"], "No customer approval right over sub-processors", [cdoc], True)

    # ---- contract terms
    C = P["contract_terms"]
    crefs = [cdoc] + amend_refs
    if not contract.customer_liability_capped:
        col.add("CON-CUSTOMER-UNCAPPED", "contract_terms", C["customer_liability_uncapped"], "Customer's liability to the vendor is uncapped", crefs, True)
    if contract.vendor_liability_cap_months_fees is not None and contract.vendor_liability_cap_months_fees < 12:
        col.add("CON-LOW-VENDOR-CAP", "contract_terms", C["vendor_cap_below_12_months_fees"],
                f"Vendor liability capped at {contract.vendor_liability_cap_months_fees} months of fees (policy minimum 12)", crefs, True)
    if contract.auto_renewal and contract.renewal_notice_days > L["renewal_notice_max_days"]:
        col.add("CON-AUTO-RENEW-LONG-NOTICE", "contract_terms", C["auto_renewal_long_notice"],
                f"Auto-renews unless cancelled {contract.renewal_notice_days} days before term end (policy maximum {L['renewal_notice_max_days']})", crefs, True)
    if not contract.termination_for_convenience:
        col.add("CON-NO-TFC", "contract_terms", C["no_termination_for_convenience"], "No customer right to terminate for convenience", crefs, True)
    if not contract.audit_rights:
        col.add("CON-NO-AUDIT-RIGHTS", "contract_terms", C["no_audit_rights"], "No customer audit rights", crefs, True)
    if contract.annual_price_escalation_pct > L["price_escalation_max_pct"]:
        col.add("CON-PRICE-ESCALATION", "contract_terms", C["price_escalation_above_limit"],
                f"Annual price escalation {contract.annual_price_escalation_pct}% exceeds policy maximum {L['price_escalation_max_pct']}%", crefs)

    # ---- financial health (latest year)
    F = P["financial_health"]
    if not f.financials:
        col.add("FIN-STATEMENTS-MISSING", "financial_health", F["statements_missing"], "No financial statements provided; financial risk unknown", [])
    else:
        if len(f.financials) < min_years:
            col.add("FIN-STATEMENTS-INCOMPLETE", "financial_health", F["statements_incomplete"], f"Only {len(f.financials)} of {min_years} required years provided", [fy.doc_id for fy in f.financials])
        fy = sorted(f.financials, key=lambda x: x.fiscal_year)[-1]
        ref = [fy.doc_id]
        if fy.current_ratio < 1.0:
            col.add("FIN-LOW-LIQUIDITY", "financial_health", F["current_ratio_below_1_0"], f"Current ratio {fy.current_ratio} in {fy.fiscal_year} (below 1.0)", ref)
        elif fy.current_ratio < 1.2:
            col.add("FIN-WEAK-LIQUIDITY", "financial_health", F["current_ratio_below_1_2"], f"Current ratio {fy.current_ratio} in {fy.fiscal_year} (below 1.2)", ref)
        if fy.debt_to_equity > 2.0:
            col.add("FIN-HIGH-LEVERAGE", "financial_health", F["debt_to_equity_above_2_0"], f"Debt-to-equity {fy.debt_to_equity} in {fy.fiscal_year} (above 2.0)", ref)
        elif fy.debt_to_equity > 1.5:
            col.add("FIN-ELEVATED-LEVERAGE", "financial_health", F["debt_to_equity_above_1_5"], f"Debt-to-equity {fy.debt_to_equity} in {fy.fiscal_year} (above 1.5)", ref)
        if fy.operating_margin_pct < 0:
            col.add("FIN-LOSS-MAKING", "financial_health", F["operating_loss"], f"Operating margin {fy.operating_margin_pct}% in {fy.fiscal_year}", ref)
        if fy.revenue_growth_pct < -10:
            col.add("FIN-REVENUE-DECLINE", "financial_health", F["revenue_decline_over_10pct"], f"Revenue fell {abs(fy.revenue_growth_pct)}% in {fy.fiscal_year}", ref)

    # ---- operational performance (renewals only)
    O = P["operational_performance"]
    ops_applicable = f.review_type == ReviewType.RENEWAL and f.performance is not None
    if ops_applicable:
        p, ref = f.performance, [f"PERF-{f.vendor_id}"]
        if p.sla_attainment_pct < 99.0:
            col.add("OPS-SLA-MISS-MAJOR", "operational_performance", O["sla_below_99_0"], f"SLA attainment {p.sla_attainment_pct}% vs target {p.sla_target_pct}%", ref)
        elif p.sla_attainment_pct < p.sla_target_pct:
            col.add("OPS-SLA-MISS-MINOR", "operational_performance", O["sla_below_target"], f"SLA attainment {p.sla_attainment_pct}% vs target {p.sla_target_pct}%", ref)
        if p.p1_incidents_12m >= 3:
            col.add("OPS-P1-INCIDENTS", "operational_performance", O["p1_incidents_3_or_more"], f"{p.p1_incidents_12m} P1 incidents in the last 12 months", ref)
        elif p.p1_incidents_12m >= 1:
            col.add("OPS-P1-SOME", "operational_performance", O["p1_incidents_1_or_2"], f"{p.p1_incidents_12m} P1 incident(s) in the last 12 months", ref)
        if p.late_delivery_pct > 10:
            col.add("OPS-LATE-DELIVERY", "operational_performance", O["late_delivery_over_10pct"], f"{p.late_delivery_pct}% of deliveries late", ref)
        if p.open_disputes > 0:
            col.add("OPS-OPEN-DISPUTE", "operational_performance", O["open_dispute"], f"{p.open_disputes} open commercial dispute(s)", ref)

    # ---- governance knockouts
    knockouts = []
    if f.debarred:
        col.add("GOV-DEBARRED", "governance", 0, "Vendor appears on the internal debarment list", ["POLICY-DEBARMENT-LIST"])
        knockouts.append(("KO-DEBARRED", "CRITICAL"))
    if f.conflict_of_interest:
        col.add("GOV-CONFLICT-OF-INTEREST", "governance", 0, f"Undisclosed conflict of interest: {f.conflict_of_interest}", ["COI-REGISTER"])
        knockouts.append(("KO-CONFLICT-OF-INTEREST", "HIGH"))
    if tier in (1, 2) and statuses[ET.SOC2_TYPE2] not in VALID and statuses[ET.ISO27001] not in VALID:
        knockouts.append(("KO-NO-SECURITY-ATTESTATION", "HIGH"))
    if personal and not contract.dpa_signed:
        knockouts.append(("KO-PERSONAL-DATA-NO-DPA", "HIGH"))

    # ---- aggregate
    applicable = {"security_compliance": True, "data_protection": personal, "contract_terms": True,
                  "financial_health": True, "operational_performance": ops_applicable}
    dims = []
    for d, w in r["weights"].items():
        pts = min(100, sum(x["points"] for x in col.findings if x["dimension"] == d))
        dims.append(dict(dimension=d, points=pts, weight=w, applicable=applicable[d],
                         triggered_rules=[x["code"] for x in col.findings if x["dimension"] == d]))
    wsum = sum(d["weight"] for d in dims if d["applicable"])
    overall = round(sum(d["points"] * d["weight"] for d in dims if d["applicable"]) / wsum, 1)
    raw_band = band_of(overall, r)
    band = raw_band
    for _, mb in knockouts:
        if BAND_ORDER.index(mb) > BAND_ORDER.index(band):
            band = mb

    req_items = [c for c in checklist if c["required"]]
    if band in ("HIGH", "CRITICAL"):
        rec = "ESCALATE_HIGH_RISK"
    elif any(c["status"] in ("MISSING", "CONTRADICTORY") for c in req_items):
        rec = "HOLD_PENDING_EVIDENCE"
    elif band == "MEDIUM" or any(c["status"] in ("EXPIRED", "EXPIRING_SOON") for c in req_items) or col.findings:
        rec = "PROCEED_WITH_CONDITIONS"
    else:
        rec = "PROCEED"
    conditions = [f"Resolve {x['code']}: {x['statement']}" for x in col.findings if x["dimension"] != "governance"] \
        if rec in ("PROCEED_WITH_CONDITIONS", "HOLD_PENDING_EVIDENCE") else []

    approvers = []
    for row in r["approval_matrix"]:
        if row["max_inr"] is None or f.annual_value_inr <= row["max_inr"]:
            approvers = list(row["approvers"])
            break
    add = r["additional_approvers"]
    if band in ("HIGH", "CRITICAL"):
        approvers.append(add["band_high_or_critical"])
    if any(x["dimension"] == "contract_terms" for x in col.findings):
        approvers.append(add["any_contract_terms_finding"])
    if any(x["dimension"] == "data_protection" for x in col.findings):
        approvers.append(add["any_data_protection_finding"])
    if f.conflict_of_interest:
        approvers.append(add["conflict_of_interest"])

    return dict(vendor_id=f.vendor_id, as_of=as_of.isoformat(), rubric_version=r["version"], tier=tier,
                checklist=checklist, contradictions=contra, findings=col.findings,
                dimensions=dims, overall=overall, raw_band=raw_band, band=band,
                knockouts=[k for k, _ in knockouts], recommendation=rec, conditions=conditions,
                required_approvers=approvers, human_decision=None)
