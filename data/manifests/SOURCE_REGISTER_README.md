# Source register — Procurement & Vendor Risk Copilot (Week 1, step 1.4)

Built 2026-11-03 from `Procurement_dataset_3.zip`, with the DPDP Rules 2025 restored from the previous upload.

## Files
| File | What it holds |
|---|---|
| `source_register.csv` | One row per raw source: slice, role, include/partial/exclude, ingest scope (page ranges, sheets, row filters), split strategy, word count in scope, estimated corpus docs, licence, notes |
| `cuad_selection.csv` | All 510 CUAD contracts with an include flag and reason, IT-term density and which risk clauses are labelled (liability cap, renewal, audit rights and so on) |
| `nda_selection.csv` | All 539 ContractNLI raw files, with the 40 sampled for the corpus (seed 42) |

## Roles
- **corpus**: chunked and indexed (BM25 + pgvector).
- **structured_seed**: loaded into PostgreSQL tables, not chunked.
- **generation_template**: used to generate synthetic vendor documents; not indexed raw.
- **eval_resource**: gold labels for retrieval and clause evaluation; kept out of the main index.
- **exclude**: duplicates, code, out-of-scope data.

## Corpus budget (target 800–1,200 documents)
| Slice | Real docs (estimated) | Synthetic still to generate | Total |
|---|---|---|---|
| Procurement policy | ~311 section-level docs | ~30 internal company policy docs | ~340 |
| Contracts | 140 (93 CUAD + 40 NDAs + 7 Common Paper) | ~80 vendor contracts and amendments with planted clause issues | ~220 |
| Compliance evidence | 0 (templates only) | ~175 (35 vendors × filled CAIQ summary, SOC 2 summary or bridge letter, ISO cert, insurance cert, pen-test summary) | ~175 |
| Performance and purchase records | 0 docs (344 IT award rows as seed) | ~210 (35 vendors × POs, invoices, SLA reports, incident logs, QBR notes, financial summary) | ~210 |
| Guidance and adversarial | ~95 (NIST 800-161 + CCM guidance) | ~25 prompt-injection and fake-PII docs | ~120 |
| **Total** | **~546** | **~520** | **~1,065** |

"Section-level doc" = a split at heading boundaries of about 2,000 words. If the policy slice crowds out the others in retrieval tests, drop POL-002 (superseded 2022 manual, 59 docs) or POL-010 (World Bank bidder guide, 15 docs) first.

## Ingestion rules
- DPDP Rules: pages 24–41 only (pages 1–23 are Hindi and extract as garbled text).
- CCM Implementation Guidelines: domains A&A, BCR, DSP, GRC, IAM, SEF and STA only (pages listed in the register).
- Replace World Bank supplier names with fictional vendor names before planting risk issues.
- Rename hash-named World Bank and UK PDFs to their titles in `documents.title`.
- Record source_id, version_date and licence on every chunk so citations carry provenance.
