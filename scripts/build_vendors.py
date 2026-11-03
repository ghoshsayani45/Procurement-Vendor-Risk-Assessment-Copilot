"""Build the 35 synthetic vendors and their ground truth (Week 1, step 1.3).

    python -m scripts.build_vendors          (run from repo root)

Design: every vendor starts from a clean, tier-appropriate profile; planted issues are then applied
as explicit modifiers. The expected outcome is computed by app.scoring.engine, and the build FAILS
unless the engine finds exactly the planted issues - so the ground truth is self-consistent.
All names, auditors, insurers and figures are fictional.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from app.schemas import (Amendment, CaiqClaims, ContractTerms, EvidenceItem, EvidenceType as ET, FinancialYear,
                         Performance, VendorFacts)
from app.scoring.engine import VALID, assess, evidence_status, load_rubric, tier_of

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ground_truth"
SEED_OUT = ROOT / "data" / "seed"
R = load_rubric()
AS_OF = date.fromisoformat(R["review_as_of"])
CR, LAKH = 10_000_000, 100_000

AUDITORS = ["Ardent Assurance LLP", "Northgate Audit Partners", "Velstrand CPA Group", "Kavach Assurance Services"]
CERT_BODIES = ["Kavach Certification Services", "Meridian Cert Ltd", "Trustline Registrars"]
INSURERS = ["Suraksha General Insurance", "Harbourline Insurance", "Bluecrest Specialty Insurance"]
PENTESTERS = ["Redfern Security Labs", "Cobaltgate Offensive Security", "Ironquill Testing"]

# ------------------------------------------------------------------------------------------------
# id, legal name, category, comparison group, HQ, review type, data access, business critical,
# annual value (INR), agreement type, planted issues (= expected engine finding codes),
# traps, adversarial, intended band, notes
D = [
 ("V001","Quillmoor People Cloud Pvt Ltd","HRMS and payroll SaaS","G01-HRMS","India","RENEWAL","SENSITIVE_PERSONAL",False,1.8*CR,"SaaS Subscription Agreement",
  [],["TRAP-SUPERSEDED-ISO"],[],"LOW","Clean benchmark for the HRMS group; an older expired ISO certificate is superseded by a current one."),
 ("V002","Brightvale HR Systems Ltd","HRMS and payroll SaaS","G01-HRMS","United Kingdom","NEW_VENDOR","SENSITIVE_PERSONAL",False,2.4*CR,"SaaS Subscription Agreement",
  ["SEC-ISO27001-EXPIRING","SEC-PENTEST-EXPIRED","DP-BREACH-NOTICE-LONG","CON-AUTO-RENEW-LONG-NOTICE","CON-PRICE-ESCALATION"],[],["ADV-FAKE-PII"],"MEDIUM",""),
 ("V003","Payvanta Workforce Solutions Pvt Ltd","HRMS and payroll SaaS","G01-HRMS","India","RENEWAL","SENSITIVE_PERSONAL",False,3.1*CR,"SaaS Subscription Agreement",
  ["SEC-SOC2_TYPE2-EXPIRED","SEC-ISO27001-EXPIRED","SEC-CAIQ-CONTRADICTION:iso_claim","DP-BREACH-NOTICE-ABSENT","OPS-SLA-MISS-MINOR","OPS-P1-INCIDENTS"],[],["ADV-INJECTION-CAIQ"],"HIGH","CAIQ still claims ISO certification after the certificate lapsed."),
 ("V004","Stratonimbus Hosting Pvt Ltd","Cloud hosting (IaaS)","G02-CLOUD","India","RENEWAL","PERSONAL",True,6.5*CR,"Cloud Services Agreement",
  [],["TRAP-AMENDMENT-FIXES-CAP"],[],"LOW","Base agreement capped vendor liability at 6 months of fees; Amendment 1 raised it to 12."),
 ("V005","Cirrolux Infrastructure Pte Ltd","Cloud hosting (IaaS)","G02-CLOUD","Singapore","NEW_VENDOR","PERSONAL",True,7.2*CR,"Cloud Services Agreement",
  ["DP-OFFSHORE-NO-SAFEGUARD","DP-NO-SUBPROCESSOR-CONTROL","CON-LOW-VENDOR-CAP","CON-NO-AUDIT-RIGHTS","SEC-BCP_DR_TEST-MISSING","SEC-PENTEST-MISSING","FIN-HIGH-LEVERAGE"],[],[],"HIGH",""),
 ("V006","Sentrivane Cyber Defence Pvt Ltd","Managed security (SOC) services","G03-MSSP","India","RENEWAL","INTERNAL",True,1.2*CR,"Managed Services Agreement",
  ["SEC-PENTEST-CRITICAL-OPEN","OPS-P1-SOME","CON-NO-TFC"],[],[],"MEDIUM",""),
 ("V007","Wardlock Security Operations LLC","Managed security (SOC) services","G03-MSSP","United States","NEW_VENDOR","INTERNAL",True,2.0*CR,"Managed Services Agreement",
  ["SEC-SOC2_TYPE2-MISSING","SEC-CAIQ-CONTRADICTION:mfa","SEC-PENTEST-CRITICAL-OPEN","FIN-LOSS-MAKING","FIN-LOW-LIQUIDITY","CON-CUSTOMER-UNCAPPED"],[],[],"CRITICAL","CAIQ claims MFA enforced; its own pentest found it is not."),
 ("V008","Orbelle CRM Inc","CRM SaaS","G04-CRM","United States","NEW_VENDOR","PERSONAL",False,45*LAKH,"SaaS Subscription Agreement",
  [],[],[],"LOW","Data hosted in the United States with contractual cross-border safeguards (not a finding)."),
 ("V009","Kestrion Customer Cloud Pvt Ltd","CRM SaaS","G04-CRM","India","RENEWAL","PERSONAL",False,80*LAKH,"SaaS Subscription Agreement",
  ["SEC-CYBER_INSURANCE-EXPIRING","CON-AUTO-RENEW-LONG-NOTICE","OPS-SLA-MISS-MINOR","OPS-LATE-DELIVERY","FIN-WEAK-LIQUIDITY"],["TRAP-FUTURE-AMENDMENT"],[],"MEDIUM","A signed amendment cutting the liability cap takes effect after the review date, so it must not be applied."),
 ("V010","Lumetric Insights GmbH","Data analytics and BI","G05-ANALYTICS","Germany","NEW_VENDOR","PERSONAL",False,1.1*CR,"SaaS Subscription Agreement",
  ["SEC-CAIQ-EXPIRED","DP-BREACH-NOTICE-LONG","CON-PRICE-ESCALATION","FIN-ELEVATED-LEVERAGE"],[],[],"MEDIUM","EU hosting with safeguards in place."),
 ("V011","Datafjord Analytics Pvt Ltd","Data analytics and BI","G05-ANALYTICS","India","RENEWAL","SENSITIVE_PERSONAL",False,2.2*CR,"Master Services Agreement",
  ["SEC-SOC2_TYPE2-MISSING","SEC-ISO27001-MISSING","SEC-CAIQ-CONTRADICTION:encryption","SEC-PENTEST-CRITICAL-OPEN","DP-NO-DPA","OPS-OPEN-DISPUTE"],[],["ADV-INJECTION-CONTRACT"],"HIGH","Two knockouts, but knockouts set a floor of HIGH; the score itself (38) is HIGH."),
 ("V012","Tessaline IT Services Pvt Ltd","IT staffing and managed services","G06-ITSERV","India","RENEWAL","INTERNAL",False,40*LAKH,"Managed Services Agreement",
  [],[],[],"LOW",""),
 ("V013","Corvanta Talent Partners Pvt Ltd","IT staffing and managed services","G06-ITSERV","India","NEW_VENDOR","INTERNAL",False,90*LAKH,"Professional Services Agreement",
  ["SEC-CYBER_INSURANCE-MISSING","CON-NO-TFC","FIN-WEAK-LIQUIDITY","FIN-REVENUE-DECLINE"],[],[],"MEDIUM",""),
 ("V014","Ferrolink Networks Pvt Ltd","Network hardware and AMC","G07-NETWORK","India","RENEWAL","NONE",False,18*LAKH,"Supply and Annual Maintenance Contract",
  [],[],[],"LOW",""),
 ("V015","Rivenhall Network Solutions Ltd","Network hardware and AMC","G07-NETWORK","United Kingdom","NEW_VENDOR","NONE",False,35*LAKH,"Supply and Annual Maintenance Contract",
  ["SEC-CAIQ-MISSING","SEC-INSURANCE-LOW","CON-PRICE-ESCALATION"],[],[],"MEDIUM",""),
 ("V016","Endura Device Management Inc","Endpoint management SaaS","G08-ENDPOINT","United States","RENEWAL","INTERNAL",True,95*LAKH,"SaaS Subscription Agreement",
  [],[],[],"LOW",""),
 ("V017","Patchwell Endpoint Systems Pvt Ltd","Endpoint management SaaS","G08-ENDPOINT","India","NEW_VENDOR","INTERNAL",True,1.4*CR,"SaaS Subscription Agreement",
  ["SEC-PENTEST-EXPIRED","SEC-BCP_DR_TEST-EXPIRED","SEC-CYBER_INSURANCE-EXPIRED","FIN-LOSS-MAKING","FIN-HIGH-LEVERAGE","CON-CUSTOMER-UNCAPPED","CON-LOW-VENDOR-CAP"],[],[],"CRITICAL","Critical on score alone, with no knockout."),
 ("V018","Scribewise AI Pvt Ltd","AI document processing","G09-AIDOC","India","NEW_VENDOR","SENSITIVE_PERSONAL",False,75*LAKH,"SaaS Subscription Agreement with AI Addendum",
  ["SEC-SOC2_TYPE2-MISSING","FIN-STATEMENTS-INCOMPLETE","FIN-LOSS-MAKING","DP-NO-SUBPROCESSOR-CONTROL"],[],[],"MEDIUM","Young company: ISO certified, no SOC 2 yet, one year of accounts."),
 ("V019","Parsenova Document Intelligence Pte Ltd","AI document processing","G09-AIDOC","Singapore","NEW_VENDOR","SENSITIVE_PERSONAL",False,1.6*CR,"SaaS Subscription Agreement with AI Addendum",
  ["DP-NO-DPA","DP-OFFSHORE-NO-SAFEGUARD","DP-BREACH-NOTICE-ABSENT","SEC-ISO27001-MISSING","SEC-SOC2_TYPE2-EXPIRED","SEC-CAIQ-CONTRADICTION:residency","CON-NO-AUDIT-RIGHTS"],[],["ADV-INJECTION-CAIQ"],"CRITICAL","CAIQ says data stays in India; the contract hosts it in Singapore."),
 ("V020","Vaultaire Backup Pvt Ltd","Backup and disaster recovery","G10-BACKUP","India","RENEWAL","PERSONAL",True,1.3*CR,"Managed Services Agreement",
  ["SEC-ISO27001-EXPIRING"],[],[],"LOW","Only a renewal reminder: ISO certificate expires within 60 days."),
 ("V021","Recoverly DR Services Ltd","Backup and disaster recovery","G10-BACKUP","United Kingdom","RENEWAL","PERSONAL",True,1.9*CR,"Managed Services Agreement",
  ["SEC-BCP_DR_TEST-MISSING","OPS-SLA-MISS-MAJOR","OPS-P1-INCIDENTS","OPS-OPEN-DISPUTE","FIN-REVENUE-DECLINE","CON-AUTO-RENEW-LONG-NOTICE"],[],[],"HIGH","A DR vendor that cannot evidence its own DR test."),
 ("V022","Hollowpine Workspace Inc","Collaboration and email SaaS","G11-COLLAB","United States","RENEWAL","PERSONAL",False,3.5*CR,"SaaS Subscription Agreement",
  [],[],[],"LOW",""),
 ("V023","Paytrove Gateway Pvt Ltd","Payment gateway","G12-PAYMENTS","India","NEW_VENDOR","SENSITIVE_PERSONAL",False,2.8*CR,"Payment Services Agreement",
  ["SEC-PENTEST-CRITICAL-OPEN","CON-PRICE-ESCALATION","FIN-ELEVATED-LEVERAGE","DP-BREACH-NOTICE-LONG"],[],[],"MEDIUM",""),
 ("V024","Coinharbor Payments Pte Ltd","Payment gateway","G12-PAYMENTS","Singapore","NEW_VENDOR","SENSITIVE_PERSONAL",False,3.3*CR,"Payment Services Agreement",
  ["SEC-ISO27001-EXPIRED","SEC-CAIQ-CONTRADICTION:iso_claim","FIN-LOW-LIQUIDITY","FIN-LOSS-MAKING","CON-LOW-VENDOR-CAP","DP-NO-SUBPROCESSOR-CONTROL"],[],[],"HIGH","SOC 2 is current, so no knockout; risk comes from the score."),
 ("V025","Meridux Telecom Pvt Ltd","Telecom and connectivity","G13-TELECOM","India","RENEWAL","NONE",True,2.1*CR,"Telecom Services Agreement",
  ["OPS-P1-SOME"],[],[],"LOW",""),
 ("V026","Skyquill Connect Pvt Ltd","Telecom and connectivity","G13-TELECOM","India","RENEWAL","NONE",False,60*LAKH,"Telecom Services Agreement",
  ["SEC-CYBER_INSURANCE-EXPIRED","OPS-SLA-MISS-MINOR","OPS-LATE-DELIVERY","CON-AUTO-RENEW-LONG-NOTICE"],[],["ADV-INJECTION-INVOICE"],"MEDIUM",""),
 ("V027","Codeweft Technologies Pvt Ltd","Software development outsourcing","G14-DEVOUT","India","RENEWAL","INTERNAL",False,1.5*CR,"Professional Services Agreement",
  ["CON-NO-AUDIT-RIGHTS","OPS-LATE-DELIVERY","FIN-WEAK-LIQUIDITY"],[],[],"LOW","Three moderate findings still score LOW; the recommendation is PROCEED_WITH_CONDITIONS, not PROCEED."),
 ("V028","Bytemarsh Software Labs Pvt Ltd","Software development outsourcing","G14-DEVOUT","India","NEW_VENDOR","INTERNAL",False,2.6*CR,"Professional Services Agreement",
  ["GOV-CONFLICT-OF-INTEREST","CON-PRICE-ESCALATION"],[],[],"HIGH","Clean on paper; the knockout comes only from the conflict-of-interest register."),
 ("V029","Learnstead Academy Pvt Ltd","E-learning SaaS","G15-ELEARN","India","NEW_VENDOR","INTERNAL",False,12*LAKH,"SaaS Subscription Agreement",
  [],[],[],"LOW","Tier 3: only CAIQ, insurance and one year of accounts required."),
 ("V030","Calldrift BPO Services Pvt Ltd","Customer support outsourcing (BPO)","G16-BPO","India","RENEWAL","SENSITIVE_PERSONAL",False,4.2*CR,"Business Process Outsourcing Agreement",
  ["DP-BREACH-NOTICE-LONG","DP-NO-SUBPROCESSOR-CONTROL","SEC-PENTEST-EXPIRED","OPS-P1-INCIDENTS","OPS-SLA-MISS-MAJOR","FIN-ELEVATED-LEVERAGE"],[],[],"HIGH",""),
 ("V031","Voxenta Contact Centres Pvt Ltd","Customer support outsourcing (BPO)","G16-BPO","India","NEW_VENDOR","SENSITIVE_PERSONAL",False,5.5*CR,"Business Process Outsourcing Agreement",
  ["SEC-SOC2_TYPE2-MISSING","SEC-ISO27001-MISSING","SEC-CAIQ-MISSING","DP-NO-DPA","FIN-STATEMENTS-MISSING","CON-CUSTOMER-UNCAPPED"],[],["ADV-FAKE-PII"],"CRITICAL","Almost no evidence supplied for a high-value, sensitive-data engagement."),
 ("V032","Keyloom Identity Inc","Identity and SSO SaaS","G17-IAM","United States","RENEWAL","PERSONAL",True,1.7*CR,"SaaS Subscription Agreement",
  [],[],[],"LOW",""),
 ("V033","Passgrove Access Pvt Ltd","Identity and SSO SaaS","G17-IAM","India","NEW_VENDOR","PERSONAL",True,90*LAKH,"SaaS Subscription Agreement",
  ["SEC-CAIQ-CONTRADICTION:mfa","SEC-BCP_DR_TEST-EXPIRED","FIN-WEAK-LIQUIDITY"],[],["ADV-INJECTION-CONTRACT"],"MEDIUM","An identity vendor whose pentest found MFA not enforced."),
 ("V034","Opticrest Surveillance Systems Pvt Ltd","CCTV and facility IoT","G18-FACILITY","India","NEW_VENDOR","PERSONAL",False,1.0*CR,"Supply and Managed Services Agreement",
  ["GOV-DEBARRED","SEC-SECURITY_ATTESTATION-MISSING","CON-NO-TFC"],[],[],"CRITICAL","On the internal debarment list after a 2025 contract breach; also holds neither SOC 2 nor ISO 27001."),
 ("V035","Gridwatch Facility Tech Pvt Ltd","CCTV and facility IoT","G18-FACILITY","India","RENEWAL","INTERNAL",False,30*LAKH,"Supply and Managed Services Agreement",
  ["SEC-CYBER_INSURANCE-EXPIRING","OPS-P1-SOME","FIN-REVENUE-DECLINE"],[],[],"LOW",""),
]

OWNERS = {"G01-HRMS":"HR Operations","G02-CLOUD":"IT Infrastructure","G03-MSSP":"Information Security","G04-CRM":"Sales Operations",
          "G05-ANALYTICS":"Data & Analytics","G06-ITSERV":"IT Service Delivery","G07-NETWORK":"IT Infrastructure","G08-ENDPOINT":"End-User Computing",
          "G09-AIDOC":"Finance Operations","G10-BACKUP":"IT Infrastructure","G11-COLLAB":"Workplace Technology","G12-PAYMENTS":"Treasury",
          "G13-TELECOM":"Network Services","G14-DEVOUT":"Engineering","G15-ELEARN":"Learning & Development","G16-BPO":"Customer Service",
          "G17-IAM":"Information Security","G18-FACILITY":"Facilities Management"}


def d(days: int) -> date:
    return AS_OF + timedelta(days=days)


def ev(vid, etype, n, **kw):
    return EvidenceItem(evidence_id=f"{vid}-{etype.value}-{n}", type=etype, doc_id=f"DOC-{vid}-{etype.value}-{n}", **kw)


def base_vendor(row, rng: random.Random) -> VendorFacts:
    (vid, name, cat, grp, hq, rtype, access, crit, value, agr, issues, traps, adv, _, notes) = row
    value = int(value)
    personal = access in ("PERSONAL", "SENSITIVE_PERSONAL")
    probe = VendorFacts(vendor_id=vid, legal_name=name, category=cat, comparison_group=grp, hq_country=hq, incorporation_year=2000,
                        employees=100, review_type=rtype, data_access=access, business_critical=crit, annual_value_inr=value,
                        business_owner=OWNERS[grp], evidence=[], contract=ContractTerms(agreement_type=agr), financials=[])
    tier = tier_of(probe, R)
    min_cov = R["evidence_rules"]["CYBER_INSURANCE"]["min_coverage_inr_by_tier"][tier]
    E = []
    has_soc2 = tier == 1 or rng.random() < 0.5
    has_iso = tier == 1 or not has_soc2 or rng.random() < 0.6
    if has_soc2:
        pe = d(-rng.randint(90, 200))
        E.append(ev(vid, ET.SOC2_TYPE2, 1, issuer=rng.choice(AUDITORS), period_start=pe - timedelta(days=365), period_end=pe, issue_date=pe + timedelta(days=45)))
    if has_iso:
        exp = d(rng.randint(200, 700))
        E.append(ev(vid, ET.ISO27001, 1, issuer=rng.choice(CERT_BODIES), issue_date=exp - timedelta(days=3 * 365), expiry_date=exp))
    if tier == 1 or rng.random() < 0.4:
        E.append(ev(vid, ET.PENTEST, 1, issuer=rng.choice(PENTESTERS), issue_date=d(-rng.randint(40, 250)), findings=["LOW_TLS_CONFIG"] if rng.random() < 0.4 else []))
    E.append(ev(vid, ET.CYBER_INSURANCE, 1, issuer=rng.choice(INSURERS), issue_date=d(-rng.randint(60, 270)), expiry_date=d(rng.randint(90, 300)),
                coverage_inr=int(min_cov * rng.choice([1.2, 1.5, 2, 2.5, 3]))))
    if tier == 1:
        E.append(ev(vid, ET.BCP_DR_TEST, 1, issuer=f"{name} (self-attested, witnessed)", issue_date=d(-rng.randint(30, 250))))
    if personal:
        E.append(ev(vid, ET.DPA, 1, issue_date=d(-rng.randint(20, 700)) if rtype == "RENEWAL" else d(-rng.randint(5, 30))))
    caiq = CaiqClaims(completed_date=d(-rng.randint(30, 200)))
    loc = {"United States": "United States", "Germany": "European Union"}.get(hq, "India") if personal else "India"
    contract = ContractTerms(agreement_type=agr, doc_id=f"DOC-{vid}-CONTRACT-1", governing_law="India",
                             vendor_liability_cap_months_fees=rng.choice([12, 12, 18, 24]), customer_liability_capped=True,
                             auto_renewal=rng.random() < 0.5, renewal_notice_days=rng.choice([30, 45, 60, 90]),
                             termination_for_convenience=True, audit_rights=True, annual_price_escalation_pct=rng.choice([0.0, 3.0, 5.0, 6.0, 7.5]),
                             breach_notification_hours=rng.choice([24, 24, 36, 48]) if personal else rng.choice([24, 48, None]),
                             data_location=loc, cross_border_safeguards=True, subprocessor_approval=True, dpa_signed=personal)
    emp = rng.choice([60, 120, 250, 600, 1500, 4000])
    rev = int(emp * rng.uniform(25, 60) * LAKH)
    fy_labels = ["FY2024-25", "FY2025-26"] if hq == "India" else ["CY2024", "CY2025"]
    fins = []
    for i, lab in enumerate(fy_labels):
        fins.append(FinancialYear(fiscal_year=lab, revenue_inr=int(rev * (0.88 if i == 0 else 1.0)), revenue_growth_pct=round(rng.uniform(5, 25), 1),
                                  operating_margin_pct=round(rng.uniform(8, 22), 1), current_ratio=round(rng.uniform(1.4, 2.5), 2),
                                  debt_to_equity=round(rng.uniform(0.2, 1.0), 2), doc_id=f"DOC-{vid}-FIN-{lab}"))
    perf = None
    cs = ce = None
    if rtype == "RENEWAL":
        perf = Performance(period=f"{(AS_OF - timedelta(days=365)).isoformat()} to {AS_OF.isoformat()}",
                           sla_attainment_pct=round(rng.uniform(99.6, 99.95), 2), p1_incidents_12m=0,
                           late_delivery_pct=round(rng.uniform(0, 6), 1), open_disputes=0)
        cs = date(rng.choice([2023, 2024]), rng.randint(1, 12), 1)
        ce = d(rng.randint(30, 120))
    return VendorFacts(vendor_id=vid, legal_name=name, category=cat, comparison_group=grp, hq_country=hq,
                       incorporation_year=rng.randint(1998, 2019), employees=emp, review_type=rtype, data_access=access,
                       business_critical=crit, annual_value_inr=value, business_owner=OWNERS[grp], contract_start=cs, contract_end=ce,
                       evidence=E, caiq=caiq, contract=contract, financials=fins, performance=perf,
                       planted_issues=[i.split(":")[0] for i in issues], traps=traps, adversarial=adv, notes=notes)


def _drop(v, etype):
    v.evidence = [e for e in v.evidence if e.type != etype]


def _get(v, etype, vid, rng, **defaults):
    for e in v.evidence:
        if e.type == etype:
            return e
    e = ev(vid, etype, 1, **defaults)
    v.evidence.append(e)
    return e


def apply_issue(v: VendorFacts, code: str, rng: random.Random, tier: int, contra: list):
    vid = v.vendor_id
    c, last = v.contract, (v.financials[-1] if v.financials else None)
    base, _, variant = code.partition(":")
    if base == "SEC-SOC2_TYPE2-EXPIRED":
        pe = d(-rng.randint(400, 520))
        e = _get(v, ET.SOC2_TYPE2, vid, rng, issuer=rng.choice(AUDITORS))
        e.period_end, e.period_start, e.issue_date = pe, pe - timedelta(days=365), pe + timedelta(days=45)
    elif base == "SEC-SOC2_TYPE2-MISSING":
        _drop(v, ET.SOC2_TYPE2)
    elif base == "SEC-ISO27001-EXPIRED":
        e = _get(v, ET.ISO27001, vid, rng, issuer=rng.choice(CERT_BODIES))
        e.expiry_date = d(-rng.randint(20, 200)); e.issue_date = e.expiry_date - timedelta(days=3 * 365)
    elif base == "SEC-ISO27001-MISSING":
        _drop(v, ET.ISO27001)
    elif base == "SEC-ISO27001-EXPIRING":
        e = _get(v, ET.ISO27001, vid, rng, issuer=rng.choice(CERT_BODIES))
        e.expiry_date = d(rng.randint(15, 50)); e.issue_date = e.expiry_date - timedelta(days=3 * 365)
    elif base == "SEC-SECURITY_ATTESTATION-MISSING":
        _drop(v, ET.SOC2_TYPE2); _drop(v, ET.ISO27001)
    elif base == "SEC-SECURITY_ATTESTATION-EXPIRED":
        _drop(v, ET.SOC2_TYPE2)
        e = _get(v, ET.ISO27001, vid, rng, issuer=rng.choice(CERT_BODIES))
        e.expiry_date = d(-rng.randint(20, 200)); e.issue_date = e.expiry_date - timedelta(days=3 * 365)
    elif base == "SEC-PENTEST-MISSING":
        _drop(v, ET.PENTEST)
    elif base == "SEC-CAIQ-MISSING":
        v.caiq = None
    elif base == "SEC-CAIQ-EXPIRED":
        v.caiq.completed_date = d(-rng.randint(400, 500))
    elif base == "SEC-CAIQ-CONTRADICTION":
        contra.append(variant)
    elif base == "SEC-PENTEST-EXPIRED":
        e = _get(v, ET.PENTEST, vid, rng, issuer=rng.choice(PENTESTERS))
        e.issue_date = d(-rng.randint(400, 550))
    elif base == "SEC-PENTEST-CRITICAL-OPEN":
        e = _get(v, ET.PENTEST, vid, rng, issuer=rng.choice(PENTESTERS), issue_date=d(-rng.randint(40, 200)))
        e.open_critical_findings = rng.randint(1, 3)
        e.findings = sorted(set(e.findings) | {"SQL_INJECTION_ADMIN_PORTAL", "OUTDATED_TLS"} if e.open_critical_findings > 1 else set(e.findings) | {"SQL_INJECTION_ADMIN_PORTAL"})
    elif base == "SEC-CYBER_INSURANCE-EXPIRED":
        e = _get(v, ET.CYBER_INSURANCE, vid, rng); e.expiry_date = d(-rng.randint(10, 120)); e.issue_date = e.expiry_date - timedelta(days=365)
    elif base == "SEC-CYBER_INSURANCE-EXPIRING":
        e = _get(v, ET.CYBER_INSURANCE, vid, rng); e.expiry_date = d(rng.randint(10, 50)); e.issue_date = e.expiry_date - timedelta(days=365)
    elif base == "SEC-CYBER_INSURANCE-MISSING":
        _drop(v, ET.CYBER_INSURANCE)
    elif base == "SEC-INSURANCE-LOW":
        min_cov = R["evidence_rules"]["CYBER_INSURANCE"]["min_coverage_inr_by_tier"][tier]
        _get(v, ET.CYBER_INSURANCE, vid, rng).coverage_inr = int(min_cov * rng.choice([0.3, 0.5, 0.6]))
    elif base == "SEC-BCP_DR_TEST-EXPIRED":
        _get(v, ET.BCP_DR_TEST, vid, rng).issue_date = d(-rng.randint(400, 600))
    elif base == "SEC-BCP_DR_TEST-MISSING":
        _drop(v, ET.BCP_DR_TEST)
    elif base == "DP-NO-DPA":
        c.dpa_signed = False; _drop(v, ET.DPA)
    elif base == "DP-BREACH-NOTICE-ABSENT":
        c.breach_notification_hours = None
    elif base == "DP-BREACH-NOTICE-LONG":
        c.breach_notification_hours = rng.choice([72, 96, 120, 168])
    elif base == "DP-OFFSHORE-NO-SAFEGUARD":
        c.data_location = {"Singapore": "Singapore", "United States": "United States"}.get(v.hq_country, "Singapore")
        c.cross_border_safeguards = False
    elif base == "DP-NO-SUBPROCESSOR-CONTROL":
        c.subprocessor_approval = False
    elif base == "CON-CUSTOMER-UNCAPPED":
        c.customer_liability_capped = False
    elif base == "CON-LOW-VENDOR-CAP":
        c.vendor_liability_cap_months_fees = rng.choice([3, 6])
    elif base == "CON-AUTO-RENEW-LONG-NOTICE":
        c.auto_renewal, c.renewal_notice_days = True, rng.choice([120, 180])
    elif base == "CON-NO-TFC":
        c.termination_for_convenience = False
    elif base == "CON-NO-AUDIT-RIGHTS":
        c.audit_rights = False
    elif base == "CON-PRICE-ESCALATION":
        c.annual_price_escalation_pct = rng.choice([10.0, 12.0, 15.0])
    elif base == "FIN-STATEMENTS-MISSING":
        v.financials = []
    elif base == "FIN-STATEMENTS-INCOMPLETE":
        v.financials = v.financials[-1:]
    elif base == "FIN-LOW-LIQUIDITY":
        last.current_ratio = round(rng.uniform(0.6, 0.95), 2)
    elif base == "FIN-WEAK-LIQUIDITY":
        last.current_ratio = round(rng.uniform(1.0, 1.18), 2)
    elif base == "FIN-HIGH-LEVERAGE":
        last.debt_to_equity = round(rng.uniform(2.2, 3.5), 2)
    elif base == "FIN-ELEVATED-LEVERAGE":
        last.debt_to_equity = round(rng.uniform(1.55, 1.95), 2)
    elif base == "FIN-LOSS-MAKING":
        last.operating_margin_pct = round(-rng.uniform(4, 15), 1)
    elif base == "FIN-REVENUE-DECLINE":
        last.revenue_growth_pct = round(-rng.uniform(12, 25), 1)
    elif base == "OPS-SLA-MISS-MAJOR":
        v.performance.sla_attainment_pct = round(rng.uniform(97.5, 98.9), 2)
    elif base == "OPS-SLA-MISS-MINOR":
        v.performance.sla_attainment_pct = round(rng.uniform(99.0, 99.4), 2)
    elif base == "OPS-P1-INCIDENTS":
        v.performance.p1_incidents_12m = rng.randint(3, 6)
    elif base == "OPS-P1-SOME":
        v.performance.p1_incidents_12m = rng.randint(1, 2)
    elif base == "OPS-LATE-DELIVERY":
        v.performance.late_delivery_pct = round(rng.uniform(12, 25), 1)
    elif base == "OPS-OPEN-DISPUTE":
        v.performance.open_disputes = 1
    elif base == "GOV-DEBARRED":
        v.debarred = True
    elif base == "GOV-CONFLICT-OF-INTEREST":
        v.conflict_of_interest = ("A Bytemarsh director is a close relative of a member of the evaluating Engineering team; "
                                  "not declared in the vendor's bid or the employee's annual declaration")
    else:
        raise ValueError(f"unknown issue {code}")


def apply_trap(v: VendorFacts, trap: str, rng: random.Random):
    vid = v.vendor_id
    if trap == "TRAP-SUPERSEDED-ISO":
        cur = next(e for e in v.evidence if e.type == ET.ISO27001)
        old = ev(vid, ET.ISO27001, 0, issuer=cur.issuer, issue_date=cur.issue_date - timedelta(days=3 * 365),
                 expiry_date=cur.issue_date - timedelta(days=1), superseded_by=cur.evidence_id)
        v.evidence.insert(0, old)
    elif trap == "TRAP-AMENDMENT-FIXES-CAP":
        v.contract.vendor_liability_cap_months_fees = 6
        v.contract.amendments.append(Amendment(amendment_id=f"{vid}-AMD-1", effective_date=d(-rng.randint(60, 200)),
                                               changes={"vendor_liability_cap_months_fees": 12}, doc_id=f"DOC-{vid}-CONTRACT-AMD-1"))
    elif trap == "TRAP-FUTURE-AMENDMENT":
        v.contract.amendments.append(Amendment(amendment_id=f"{vid}-AMD-1", effective_date=v.contract_end + timedelta(days=1),
                                               changes={"vendor_liability_cap_months_fees": 6}, doc_id=f"DOC-{vid}-CONTRACT-AMD-1"))
    else:
        raise ValueError(trap)


def set_caiq_claims(v: VendorFacts, contra: list):
    if not v.caiq:
        return
    st = {et: evidence_status(v, et, R, AS_OF)[0] for et in (ET.SOC2_TYPE2, ET.ISO27001)}
    v.caiq.soc2_type2 = st[ET.SOC2_TYPE2] in VALID
    v.caiq.iso27001_certified = st[ET.ISO27001] in VALID
    v.caiq.data_residency = v.contract.data_location
    pen = next((e for e in v.evidence if e.type == ET.PENTEST), None)
    for var in contra:
        if var == "iso_claim":
            v.caiq.iso27001_certified = True
        elif var == "soc2_claim":
            v.caiq.soc2_type2 = True
        elif var == "residency":
            v.caiq.data_residency = "India"
        elif var == "encryption":
            pen = pen or _get(v, ET.PENTEST, v.vendor_id, random.Random(0), issuer=PENTESTERS[0], issue_date=d(-90))
            pen.findings = sorted(set(pen.findings) | {"UNENCRYPTED_DATA_AT_REST"})
            v.caiq.encryption_at_rest = True
        elif var == "mfa":
            pen = pen or _get(v, ET.PENTEST, v.vendor_id, random.Random(0), issuer=PENTESTERS[0], issue_date=d(-90))
            pen.findings = sorted(set(pen.findings) | {"MFA_NOT_ENFORCED"})
            v.caiq.mfa_enforced = True
        else:
            raise ValueError(var)


def build():
    vendors, outcomes, problems = [], [], []
    for row in D:
        rng = random.Random(f"pvrc-{row[0]}")
        v = base_vendor(row, rng)
        tier = tier_of(v, R)
        contra: list = []
        for code in row[10]:
            apply_issue(v, code, rng, tier, contra)
        for t in row[11]:
            apply_trap(v, t, rng)
        set_caiq_claims(v, contra)
        if len(v.financials) == 2:  # keep the prior year's revenue consistent with the latest year's stated growth
            v.financials[0].revenue_inr = round(v.financials[1].revenue_inr / (1 + v.financials[1].revenue_growth_pct / 100))
        v = VendorFacts.model_validate(v.model_dump())  # re-validate after mutation
        out = assess(v, R, AS_OF)
        found = {f["code"] for f in out["findings"]}
        planted = set(v.planted_issues)
        if found != planted:
            problems.append(f"{v.vendor_id}: planted-not-found={sorted(planted - found)} found-not-planted={sorted(found - planted)}")
        if out["band"] != row[13]:
            problems.append(f"{v.vendor_id}: intended {row[13]} but engine says {out['band']} (score {out['overall']})")
        vendors.append(v)
        outcomes.append(out)
    return vendors, outcomes, problems


DOC_KIND = {ET.SOC2_TYPE2: "SOC 2 Type II report summary", ET.ISO27001: "ISO/IEC 27001 certificate", ET.PENTEST: "Penetration test executive summary",
            ET.CYBER_INSURANCE: "Cyber insurance certificate", ET.BCP_DR_TEST: "BCP/DR test report", ET.DPA: "Data processing agreement"}
ADV_TARGET = {"ADV-INJECTION-CAIQ": "CAIQ", "ADV-INJECTION-CONTRACT": "CONTRACT", "ADV-INJECTION-INVOICE": "INVOICE", "ADV-FAKE-PII": "PERF"}


def document_plan(vendors):
    """Documents step 1.4 must generate per vendor, with the facts each must state."""
    rows = []
    for v in vendors:
        def add(doc_id, slice_, kind, facts, issues=(), adv=""):
            rows.append(dict(doc_id=doc_id, vendor_id=v.vendor_id, slice=slice_, doc_kind=kind, must_state=facts,
                             planted_issues=";".join(issues), adversarial=adv))
        adv_for = lambda target: ";".join(a for a in v.adversarial if ADV_TARGET[a] == target)
        for e in v.evidence:
            facts = {k: str(val) for k, val in e.model_dump(exclude={"doc_id", "type"}).items() if val not in (None, [], 0, "")}
            iss = [i for i in v.planted_issues if e.type.value in i or (e.type == ET.CYBER_INSURANCE and i == "SEC-INSURANCE-LOW")
                   or (e.type == ET.PENTEST and i == "SEC-PENTEST-CRITICAL-OPEN")]
            if e.type == ET.DPA:
                add(e.doc_id, "contracts", DOC_KIND[e.type], json.dumps(facts), iss)
            else:
                add(e.doc_id, "compliance_evidence", DOC_KIND[e.type], json.dumps(facts), iss)
        if v.caiq:
            add(f"DOC-{v.vendor_id}-CAIQ-1", "compliance_evidence", "Completed CAIQ v4.1 (domain summaries)", v.caiq.model_dump_json(),
                [i for i in v.planted_issues if i.startswith("SEC-CAIQ")], adv_for("CAIQ"))
        c = v.contract
        cfacts = c.model_dump(exclude={"amendments", "doc_id"})
        add(c.doc_id, "contracts", c.agreement_type, json.dumps(cfacts),
            [i for i in v.planted_issues if i.startswith(("CON-", "DP-"))], adv_for("CONTRACT"))
        for a in c.amendments:
            add(a.doc_id, "contracts", "Contract amendment", json.dumps({"effective_date": str(a.effective_date), **a.changes}), [], "")
        for fy in v.financials:
            add(fy.doc_id, "performance_purchase_records", "Financial statement summary", fy.model_dump_json(exclude={"doc_id"}),
                [i for i in v.planted_issues if i.startswith("FIN-")] if fy is v.financials[-1] else [])
        if v.performance:
            add(f"DOC-{v.vendor_id}-PERF-1", "performance_purchase_records", "Quarterly business review and SLA report (trailing 12 months)",
                v.performance.model_dump_json(), [i for i in v.planted_issues if i.startswith("OPS-")], adv_for("PERF"))
            add(f"DOC-{v.vendor_id}-PO-1", "performance_purchase_records", "Purchase orders and invoices (last 4 quarters)",
                json.dumps({"annual_value_inr": v.annual_value_inr}), [], adv_for("INVOICE"))
        elif "ADV-FAKE-PII" in v.adversarial:
            add(f"DOC-{v.vendor_id}-PROPOSAL-1", "performance_purchase_records", "Vendor proposal with staffing plan",
                json.dumps({"annual_value_inr": v.annual_value_inr}), [], "ADV-FAKE-PII")
    return rows


def main():
    vendors, outcomes, problems = build()
    if problems:
        raise SystemExit("Ground truth inconsistent:\n  " + "\n  ".join(problems))
    OUT.mkdir(parents=True, exist_ok=True)
    SEED_OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "vendors.json").write_text(json.dumps([v.model_dump(mode="json") for v in vendors], indent=2))
    (OUT / "expected_outcomes.json").write_text(json.dumps(outcomes, indent=2))
    with open(OUT / "vendor_summary.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["vendor_id", "legal_name", "category", "comparison_group", "hq_country", "review_type", "data_access", "business_critical",
                    "annual_value_inr", "tier", "overall_score", "raw_band", "band", "knockouts", "recommendation", "required_approvers",
                    "checklist_not_verified", "planted_issues", "traps", "adversarial"])
        for v, o in zip(vendors, outcomes):
            nv = [f"{c['item']}={c['status']}" for c in o["checklist"] if c["required"] and c["status"] != "VERIFIED"]
            w.writerow([v.vendor_id, v.legal_name, v.category, v.comparison_group, v.hq_country, v.review_type.value, v.data_access.value,
                        v.business_critical, v.annual_value_inr, o["tier"], o["overall"], o["raw_band"], o["band"], ";".join(o["knockouts"]),
                        o["recommendation"], ";".join(o["required_approvers"]), ";".join(nv), ";".join(v.planted_issues),
                        ";".join(v.traps), ";".join(v.adversarial)])
    plan = document_plan(vendors)
    with open(OUT / "document_plan.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=plan[0].keys()); w.writeheader(); w.writerows(plan)
    # database seeds (tables from the solution document)
    with open(SEED_OUT / "vendors.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["id", "name", "category", "status", "owner"])
        for v in vendors:
            w.writerow([v.vendor_id, v.legal_name, v.category, "ACTIVE" if v.review_type.value == "RENEWAL" else "PROSPECT", v.business_owner])
    with open(SEED_OUT / "financial_metrics.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["vendor_id", "period", "metric", "value", "source"])
        for v in vendors:
            for fy in v.financials:
                for m in ("revenue_inr", "revenue_growth_pct", "operating_margin_pct", "current_ratio", "debt_to_equity"):
                    w.writerow([v.vendor_id, fy.fiscal_year, m, getattr(fy, m), fy.doc_id])
    from collections import Counter
    print("bands:", dict(Counter(o["band"] for o in outcomes)))
    print("tiers:", dict(Counter(o["tier"] for o in outcomes)))
    print("recommendations:", dict(Counter(o["recommendation"] for o in outcomes)))
    print("documents planned:", len(plan))


if __name__ == "__main__":
    main()
