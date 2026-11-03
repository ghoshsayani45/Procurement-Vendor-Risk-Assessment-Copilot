# Manifests: what is in corpus v1 and where it came from

Corpus v1 was frozen on 2026-11-03 (Git tag `corpus-v1`): **1,053 documents**, about 1.73 million words. That is inside the 500–2,000 limit and the team's 800–1,200 target.

| Slice | Real | Synthetic | Total | Plan target |
|---|---|---|---|---|
| Procurement policy | 353 section docs (GFR, Goods Manuals 2022/2024, Non-Consultancy Manual 2025, DPDP Act + Rules, UK SAF, World Bank) | 8 internal policies of the fictional buyer, Indrapath Technologies Ltd | 361 | 150–250 (over; see note) |
| Contracts | 140 (93 CUAD, 40 NDAs, 7 Common Paper templates) | 55 (35 vendor contracts, 18 DPAs, 2 amendments) | 195 | 200–350 |
| Compliance evidence | — | 163 (CAIQ responses, SOC 2 summaries, ISO certificates, pentest summaries, insurance certificates, BCP/DR reports) | 163 | 150–250 |
| Performance and purchase records | — | 210 (financial statements, QBR/SLA reports, incident logs, POs, invoices, proposals) | 210 | 250–400 |
| Guidance | 116 (NIST SP 800-161r1, CCM v4.1 guidance in 7 domains) | — | 116 | 100–150 (with adversarial) |
| Adversarial | — | 8 standalone (approval pressure, unverified claims, hidden instructions, spoofed policy, secrets request, PII sample), plus 7 payloads embedded in vendor documents | 8 | (counted with guidance) |

Note: the policy slice is large because the Indian procurement manuals are long. If retrieval tests in step 2.4 show it crowding out vendor evidence, drop `POL-002` (superseded 2022 manual, 67 docs) first.

## Files
| File | What it is | In Git |
|---|---|---|
| `source_register.csv` | Every raw source, with role, include decision, ingest scope (page ranges, sheets, filters), licence and notes | yes |
| `cuad_selection.csv`, `nda_selection.csv` | Which CUAD contracts (93/510) and ContractNLI NDAs (40/539) are in the corpus, and why | yes |
| `synthetic_docs.csv` | All 436 synthetic vendor and adversarial documents (the 8 policies are in `data/synthetic/policy/`): type, vendor, planted issues, adversarial flags | yes |
| `corpus_v1_manifest.csv` | **The frozen snapshot.** One row per corpus document: metadata, word count and SHA-1 of the text | yes |
| `SOURCE_REGISTER_README.md` | Notes from when the register was built (pre-ingestion estimates) | yes |
| `../processed/corpus_v1.jsonl` | The documents with text (≈ 12 MB); rebuild with `make ingest` | no |

## Rebuild and verify
```bash
make corpus                         # ground truth -> policies -> synthetic docs (validated) -> ingest
python -m scripts.retrieval_smoke_test
git diff --stat data/manifests/corpus_v1_manifest.csv   # empty diff = identical corpus
```
The pipeline is deterministic. The same raw data and code reproduce the same SHA-1 for every document.
