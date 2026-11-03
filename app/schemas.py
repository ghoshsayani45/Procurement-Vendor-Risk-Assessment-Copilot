"""Shared schemas for the Procurement & Vendor Risk Assessment Copilot (Week 1, step 1.2).

One source of truth for prompts (JSON schema), tools, the API, the UI and evaluation.
Two groups:
  1. Vendor facts  - the structured record a vendor's documents describe (ground truth, DB seed, tool output).
  2. Copilot I/O   - request, plan, tool calls, citations, findings, checklist, score, report, refusal.
Pydantic v2.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # small models invent fields; reject them


# ============================================================ enums
class ReviewType(str, Enum):
    NEW_VENDOR = "NEW_VENDOR"
    RENEWAL = "RENEWAL"


class RequestKind(str, Enum):
    FULL_REVIEW = "FULL_REVIEW"          # produce a complete assessment report
    COMPARISON = "COMPARISON"            # side-by-side scorecard of 2-3 vendors
    QUESTION = "QUESTION"                # single lookup / follow-up ("what is X's liability cap?")


class DataAccess(str, Enum):
    NONE = "NONE"
    INTERNAL = "INTERNAL"
    PERSONAL = "PERSONAL"
    SENSITIVE_PERSONAL = "SENSITIVE_PERSONAL"


class EvidenceType(str, Enum):
    SOC2_TYPE2 = "SOC2_TYPE2"
    ISO27001 = "ISO27001"
    CAIQ = "CAIQ"
    PENTEST = "PENTEST"
    CYBER_INSURANCE = "CYBER_INSURANCE"
    BCP_DR_TEST = "BCP_DR_TEST"
    DPA = "DPA"
    FINANCIALS = "FINANCIALS"
    SECURITY_ATTESTATION = "SECURITY_ATTESTATION"  # tier 2: SOC2_TYPE2 or ISO27001


class ChecklistStatus(str, Enum):
    VERIFIED = "VERIFIED"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"
    CONTRADICTORY = "CONTRADICTORY"
    NOT_REQUIRED = "NOT_REQUIRED"


class Dimension(str, Enum):
    SECURITY_COMPLIANCE = "security_compliance"
    DATA_PROTECTION = "data_protection"
    CONTRACT_TERMS = "contract_terms"
    FINANCIAL_HEALTH = "financial_health"
    OPERATIONAL_PERFORMANCE = "operational_performance"
    GOVERNANCE = "governance"  # knockouts: debarment, conflict of interest


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Recommendation(str, Enum):
    PROCEED = "PROCEED"
    PROCEED_WITH_CONDITIONS = "PROCEED_WITH_CONDITIONS"
    HOLD_PENDING_EVIDENCE = "HOLD_PENDING_EVIDENCE"
    ESCALATE_HIGH_RISK = "ESCALATE_HIGH_RISK"


class Behaviour(str, Enum):
    ANSWER = "ANSWER"
    PARTIAL = "PARTIAL"      # step/token budget hit or a tool failed; show what is known
    CLARIFY = "CLARIFY"      # vendor ambiguous or required input missing
    REFUSE = "REFUSE"


class RefusalCategory(str, Enum):
    APPROVAL_OR_COMMITMENT = "APPROVAL_OR_COMMITMENT"      # approve vendor, sign, award, change payment terms
    LEGAL_ADVICE = "LEGAL_ADVICE"                          # binding legal determinations
    ACCESS_CONTROL_BYPASS = "ACCESS_CONTROL_BYPASS"        # restricted documents, other teams' cases
    PII_EXPOSURE = "PII_EXPOSURE"                          # reveal personal data found in documents
    SECRETS = "SECRETS"                                    # credentials, system prompt, API keys
    SCORE_MANIPULATION = "SCORE_MANIPULATION"              # "make vendor X low risk", hide findings
    OUT_OF_SCOPE = "OUT_OF_SCOPE"                          # unrelated tasks, external web research, investment advice


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ============================================================ 1. vendor facts
class EvidenceItem(_Strict):
    evidence_id: str
    type: EvidenceType
    doc_id: Optional[str] = None              # corpus document carrying this evidence
    issuer: Optional[str] = None              # auditor / certification body / insurer
    issue_date: Optional[date] = None
    period_start: Optional[date] = None       # SOC 2 observation period
    period_end: Optional[date] = None
    expiry_date: Optional[date] = None        # ISO cert, insurance
    coverage_inr: Optional[int] = None        # insurance
    open_critical_findings: int = 0           # pentest
    findings: list[str] = Field(default_factory=list)  # pentest finding codes, e.g. UNENCRYPTED_DATA_AT_REST
    superseded_by: Optional[str] = None       # evidence_id of the newer version


class CaiqClaims(_Strict):
    completed_date: Optional[date] = None
    soc2_type2: bool = False
    iso27001_certified: bool = False
    encryption_at_rest: bool = True
    mfa_enforced: bool = True
    data_residency: str = "India"
    subprocessors_disclosed: bool = True


class Amendment(_Strict):
    amendment_id: str
    effective_date: date
    changes: dict  # field -> new value, applied in date order on top of base terms
    doc_id: Optional[str] = None


class ContractTerms(_Strict):
    agreement_type: str
    doc_id: Optional[str] = None
    governing_law: str = "India"
    vendor_liability_cap_months_fees: Optional[int] = 12   # None = vendor liability uncapped
    customer_liability_capped: bool = True
    auto_renewal: bool = False
    renewal_notice_days: int = 30
    termination_for_convenience: bool = True
    audit_rights: bool = True
    annual_price_escalation_pct: float = 5.0
    breach_notification_hours: Optional[int] = 24          # None = clause absent
    data_location: str = "India"
    cross_border_safeguards: bool = True
    subprocessor_approval: bool = True
    dpa_signed: bool = True
    amendments: list[Amendment] = Field(default_factory=list)


class FinancialYear(_Strict):
    fiscal_year: str                # e.g. "FY2025-26"
    revenue_inr: int
    revenue_growth_pct: float
    operating_margin_pct: float
    current_ratio: float
    debt_to_equity: float
    doc_id: Optional[str] = None


class Performance(_Strict):
    period: str                     # trailing 12 months label
    sla_target_pct: float = 99.5
    sla_attainment_pct: float
    p1_incidents_12m: int
    late_delivery_pct: float
    open_disputes: int = 0


class VendorFacts(_Strict):
    vendor_id: str
    legal_name: str
    category: str
    comparison_group: str
    hq_country: str
    incorporation_year: int
    employees: int
    review_type: ReviewType
    data_access: DataAccess
    business_critical: bool
    annual_value_inr: int
    business_owner: str
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    evidence: list[EvidenceItem]
    caiq: Optional[CaiqClaims] = None
    contract: ContractTerms
    financials: list[FinancialYear]
    performance: Optional[Performance] = None
    debarred: bool = False
    conflict_of_interest: Optional[str] = None
    planted_issues: list[str] = Field(default_factory=list)
    traps: list[str] = Field(default_factory=list)
    adversarial: list[str] = Field(default_factory=list)
    notes: str = ""


# ============================================================ 2. copilot I/O
class ReviewRequest(_Strict):
    request_kind: RequestKind
    review_type: Optional[ReviewType] = None
    vendor_ids: list[str] = Field(min_length=1, max_length=3)
    question: Optional[str] = None
    requester_role: Literal["procurement_analyst", "risk_reviewer", "category_manager", "legal_finance_reviewer"]
    as_of: date = date(2026, 11, 1)


ToolName = Literal["vendor_search", "document_search", "compliance_checker", "financial_risk_calculator", "vendor_compare"]


class PlanStep(_Strict):
    step: int = Field(ge=1, le=6)
    tool: ToolName
    arguments: dict
    purpose: str = Field(max_length=200)


class Plan(_Strict):
    review_template: Literal["new_vendor_full", "renewal_full", "comparison", "single_question"]
    steps: list[PlanStep] = Field(min_length=1, max_length=6)


class ToolResult(_Strict):
    tool: ToolName
    ok: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    latency_ms: Optional[int] = None


class Citation(_Strict):
    source_id: str                 # chunk id, or "tool:<name>" for computed values
    doc_id: Optional[str] = None
    title: Optional[str] = None
    document_date: Optional[date] = None
    evidence_type: Optional[EvidenceType] = None
    snippet: Optional[str] = Field(default=None, max_length=400)


class Finding(_Strict):
    code: str                      # rubric rule code, e.g. CON-AUTO-RENEW-LONG-NOTICE
    dimension: Dimension
    severity: Severity
    kind: Literal["observation", "interpretation", "recommendation"]
    statement: str = Field(max_length=500)
    citations: list[Citation] = Field(min_length=1)   # uncited findings are rejected
    needs_legal_review: bool = False


class ChecklistItem(_Strict):
    item: EvidenceType
    required: bool
    status: ChecklistStatus
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = Field(max_length=300)


class DimensionScore(_Strict):
    dimension: Dimension
    points: int = Field(ge=0, le=100)
    weight: float
    applicable: bool = True
    triggered_rules: list[str] = Field(default_factory=list)


class RiskScore(_Strict):
    overall: float = Field(ge=0, le=100)
    band: RiskBand
    raw_band: RiskBand             # band before knockouts
    dimensions: list[DimensionScore]
    knockouts: list[str] = Field(default_factory=list)
    rubric_version: str = "1.0"


class ApprovalRouting(_Strict):
    required_approvers: list[str]
    human_decision: Optional[Literal["APPROVED", "REJECTED", "MORE_INFO"]] = None  # always None from the copilot
    decided_by: Optional[str] = None

    @model_validator(mode="after")
    def copilot_never_decides(self):
        if self.human_decision is not None and not self.decided_by:
            raise ValueError("human_decision requires decided_by (a named person, never the copilot)")
        return self


class Report(_Strict):
    behaviour: Literal[Behaviour.ANSWER, Behaviour.PARTIAL]
    vendor_id: str
    review_type: ReviewType
    as_of: date
    tier: Literal[1, 2, 3]
    summary: str = Field(max_length=800)
    findings: list[Finding]
    checklist: list[ChecklistItem]
    score: RiskScore
    recommendation: Recommendation
    conditions: list[str] = Field(default_factory=list)
    approval: ApprovalRouting
    gaps_and_uncertainties: list[str] = Field(default_factory=list)
    partial_reason: Optional[str] = None  # set when behaviour == PARTIAL


class ComparisonRow(_Strict):
    vendor_id: str
    tier: Literal[1, 2, 3]
    overall: float
    band: RiskBand
    dimension_points: dict[str, int]
    key_findings: list[str]


class ComparisonResult(_Strict):
    behaviour: Literal[Behaviour.ANSWER, Behaviour.PARTIAL]
    rows: list[ComparisonRow] = Field(min_length=2, max_length=3)
    caveats: list[str] = Field(default_factory=list)


class Answer(_Strict):
    behaviour: Literal[Behaviour.ANSWER, Behaviour.PARTIAL]
    answer: str = Field(max_length=1200)
    citations: list[Citation] = Field(min_length=1)


class Clarification(_Strict):
    behaviour: Literal[Behaviour.CLARIFY]
    question: str = Field(max_length=300)
    options: list[str] = Field(default_factory=list, max_length=5)


class Refusal(_Strict):
    behaviour: Literal[Behaviour.REFUSE]
    category: RefusalCategory
    message: str = Field(max_length=400)
    route_to: Optional[str] = None   # human role who can act, e.g. "Procurement Committee"
    audit_event: bool = True


CopilotResponse = Union[Report, ComparisonResult, Answer, Clarification, Refusal]
