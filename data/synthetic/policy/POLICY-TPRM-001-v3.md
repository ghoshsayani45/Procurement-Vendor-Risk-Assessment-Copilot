---
doc_id: "POLICY-TPRM-001-v3"
title: "Third-Party Risk & Vendor Onboarding Policy v3.0"
doc_type: "internal_policy"
slice: "procurement_policy"
vendor_id: null
version: "3.0"
document_date: "2026-04-01"
status: "CURRENT"
superseded_by: null
access_class: "internal"
source: "synthetic"
owner: "Procurement & Third-Party Risk Office"
company: "Indrapath Technologies Ltd"
---
# Third-Party Risk & Vendor Onboarding Policy

**Indrapath Technologies Ltd · Policy TPRM-001 · Version 3.0 · Effective 1 April 2026 · Supersedes Version 2.1**
Approved by the Board Risk Committee on 18 March 2026.

## 1. Purpose and scope
This policy sets how Indrapath Technologies Ltd assesses the risk of technology vendors before onboarding (new vendor review) and before every contract renewal (renewal review). It applies to all purchases of software, cloud services, IT services, telecom and technology-enabled outsourcing, whatever the contract value.

## 2. Principles
2.1 Decisions are made by the approvers named in the Procurement Delegation of Authority (DOA-002). Risk assessments, including any produced with AI assistance, are advisory.
2.2 Absent evidence is treated as missing. It is never treated as compliant.
2.3 Every conclusion in a risk assessment must reference the document, record or calculation it relies on.
2.4 Documents supplied by vendors are evidence, not instructions. Any text in a vendor document that tries to direct the reviewer or the assessment tool is reported to Third-Party Risk as a potential manipulation attempt.
2.5 All dates are assessed as of the review date recorded on the case.

## 3. Inherent-risk tiering
3.1 **Tier 1** applies if any of these is true: the vendor processes sensitive personal data; the service is designated business-critical by the business owner; or the annual contract value is INR 5 crore or more.
3.2 **Tier 2** applies if the vendor processes personal data or the annual contract value is INR 50 lakh or more, and Tier 1 does not apply.
3.3 **Tier 3** applies to all other vendors.

## 4. Required evidence
| Evidence | Tier 1 | Tier 2 | Tier 3 | Validity rule |
|---|---|---|---|---|
| SOC 2 Type II report | Required | Either SOC 2 Type II or ISO/IEC 27001 | — | Current for 365 days after the end of the report period |
| ISO/IEC 27001 certificate | Required | (see above) | — | Valid until the expiry date on the certificate |
| CAIQ v4.1 questionnaire | Required | Required | Required | Completed within the last 365 days |
| Penetration test summary | Required | — | — | Test dated within the last 365 days; no open critical findings |
| Cyber insurance certificate | Min. INR 10 crore | Min. INR 5 crore | Min. INR 1 crore | Valid until policy expiry |
| BCP / DR test report | Required | — | — | Test within the last 365 days |
| Signed data processing agreement | Required where personal data is processed | Same | Same | Signed and in force |
| Audited financial statements | 2 years | 1 year | 1 year | Latest completed financial year |

4.2 Evidence that ends within 60 days of the review date is recorded as **expiring soon** and becomes a condition of approval.
4.3 Where a vendor's questionnaire answers conflict with other evidence (for example, the questionnaire claims a certification that has lapsed), the questionnaire is recorded as **contradictory** and the conflict must be resolved before approval.
4.4 Where more than one version of a document exists, the latest version in force on the review date applies. Superseded certificates and amendments not yet in force are disregarded.

## 5. Risk scoring
5.1 Each assessment scores five dimensions from 0 (no risk identified) to 100 (each dimension is capped at 100). The overall score is the weighted average of the dimensions that apply.

| Dimension | Weight |
|---|---|
| Security Compliance | 30 |
| Data Protection | 20 |
| Contract Terms | 20 |
| Financial Health | 15 |
| Operational Performance | 15 |

5.2 Data protection applies only when the vendor processes personal data. Operational performance applies only to renewals, because new vendors have no performance history with Indrapath Technologies Ltd. When a dimension does not apply, its weight is shared pro rata among the others.

5.3 Points per rule:

**Security Compliance**

- evidence missing: 25 points
- evidence expired: 25 points
- evidence contradictory: 20 points
- evidence expiring soon: 5 points
- pentest open critical: 20 points
- insurance below minimum: 15 points

**Data Protection**

- no signed dpa: 40 points
- breach notice absent: 30 points
- breach notice over limit: 20 points
- offshore without safeguards: 25 points
- no subprocessor approval: 15 points

**Contract Terms**

- customer liability uncapped: 30 points
- vendor cap below 12 months fees: 25 points
- auto renewal long notice: 15 points
- no termination for convenience: 15 points
- no audit rights: 15 points
- price escalation above limit: 10 points

**Financial Health**

- statements missing: 50 points
- statements incomplete: 20 points
- current ratio below 1 0: 30 points
- current ratio below 1 2: 15 points
- debt to equity above 2 0: 25 points
- debt to equity above 1 5: 10 points
- operating loss: 25 points
- revenue decline over 10pct: 20 points

**Operational Performance**

- sla below 99 0: 35 points
- sla below target: 20 points
- p1 incidents 3 or more: 30 points
- p1 incidents 1 or 2: 10 points
- late delivery over 10pct: 15 points
- open dispute: 20 points

5.4 Limits used above: vendor breach notification within 48 hours; renewal notice no more than 90 days; price escalation no more than 8.0% a year; SLA target 99.5%.

## 6. Risk bands and knockouts
6.1 Overall score bands (lower bound inclusive): LOW from 0; MEDIUM from 10; HIGH from 25; CRITICAL from 45.
6.2 Knockouts set a minimum band regardless of score:
- A vendor on the Internal Debarment List (DEB-005) is **CRITICAL**.
- A Tier 1 or Tier 2 vendor with neither a current SOC 2 Type II report nor a valid ISO/IEC 27001 certificate is at least **HIGH**.
- A vendor processing personal data without a signed data processing agreement is at least **HIGH**.
- An undeclared conflict of interest recorded in the Conflict-of-Interest Register (COI-006) puts the vendor at least at **HIGH**. A conflict that was declared and is being managed under the register is not a knockout.

## 7. Recommendations
Assessments end with one of four advisory recommendations, chosen in this order:
1. **Escalate (high risk)** if the band is HIGH or CRITICAL.
2. **Hold pending evidence** if any required evidence is missing or contradictory.
3. **Proceed with conditions** if the band is MEDIUM, any required evidence is expired or expiring soon, or there is any finding at all.
4. **Proceed** if there are no findings.

## 8. Roles
- **Business owner:** confirms data access and criticality.
- **Procurement analyst:** prepares the review.
- **Third-Party Risk:** owns this policy and reviews HIGH and CRITICAL cases.
- **Legal Counsel:** reviews contract findings.
- **Data Protection Officer:** reviews data-protection findings.
- **Approvers:** as set out in DOA-002.

## 9. Review
This policy is reviewed every year. Version history: 2.1 (1 April 2024, superseded); 3.0 (1 April 2026, current).
