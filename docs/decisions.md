# Decision log

| # | Date | Decision | Why | Status |
|---|---|---|---|---|
| D1 | 2026-11-03 | Fixed review as-of date 2026-11-01 for all eval_v1 queries | Expiry checks must be reproducible; "today" changes daily | Proposed |
| D2 | 2026-11-03 | Scores computed only by the deterministic engine; the LLM explains them | 8B models make arithmetic errors; score reproducibility target is ≥ 0.95 | Proposed |
| D3 | 2026-11-03 | Bands LOW < 10 ≤ MEDIUM < 25 ≤ HIGH < 45 ≤ CRITICAL | Calibrated on the 35-vendor set to give a 13/10/7/5 mix | Proposed |
| D4 | 2026-11-03 | Knockouts set minimum bands (debarred → CRITICAL; no attestation, no DPA, COI → HIGH) | Some single facts must override a good average | Proposed |
| D5 | 2026-11-03 | Vendor breach-notice limit 48 h | Leaves room for the company's 72 h duty under DPDP Rules 2025 r.7 | Proposed |
| D6 | 2026-11-03 | Missing evidence = MISSING and scores like expired evidence | "Missing is not compliant" (spec section 5) | Proposed |
| D7 | 2026-11-03 | Tier thresholds ₹5 crore / ₹50 lakh; approval limits ₹25 lakh / ₹5 crore | Synthetic internal policy; to be written into the step 1.4 policy docs | Proposed |
| D8 | 2026-11-03 | Corpus documents are section-level (long PDFs split at headings into ~1,500–3,000 words); retrieval chunking is decided separately in step 2.2 | Keeps document counts meaningful and citations readable | Proposed |
| D9 | 2026-11-03 | Synthetic documents are rendered from `vendors.json` by templates with seeded wording variants, not by an LLM | Guarantees documents never contradict the ground truth; no token quota spent; fully reproducible | Proposed |
| D10 | 2026-11-03 | Debarment list and COI register are `internal`, not `restricted` | The copilot must read them to apply knockouts; revisit if role-based access is added | Proposed |
| D11 | 2026-11-03 | Emails, press releases, web pages and drafts are not evidence (spec rule 9) | Enables the social-engineering and unverified-claim tests | Proposed |
