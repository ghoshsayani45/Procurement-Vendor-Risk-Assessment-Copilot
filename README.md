# Procurement & Vendor Risk Assessment Copilot

A Track B capstone (Executive PG Programme in Generative AI and Agentic AI). It is a multi-agent copilot that assesses technology vendors for onboarding and renewal, built on a hosted ≤8B model. It retrieves cited evidence, applies a deterministic risk rubric, and routes every decision to a human approver.

## Status
| Week 1 step | Status | Where |
|---|---|---|
| Day 0 setup | Done (endpoint values still to fill in `.env`) | `.env.example`, `app/llm_client.py`, `docker/`, `app/db/schema.sql` |
| 1.1 Task specification | Done; decisions D1–D11 need team sign-off | `docs/spec.md`, `docs/decisions.md` |
| 1.2 Rubric and schemas | Done | `app/scoring/`, `app/schemas.py`, `schemas/` |
| 1.3 Synthetic vendor set | Done (35 vendors) | `data/ground_truth/` |
| 1.4 Corpus | Done; **corpus v1 frozen: 1,053 documents** | `data/synthetic/`, `data/manifests/`, `scripts/ingest.py` |
| 1.5 Evaluation set (80 queries) | Next | `data/evaluation/` |
| 1.6–1.7 Prompting baseline | Needs the course endpoint | — |
| 1.8 Retrieval baselines | Smoke test passes (10/10); full baseline after 1.5 | `scripts/retrieval_smoke_test.py` |

## Quick start
```bash
git clone <repo> && cd procurement-vendor-risk-copilot
make setup && source .venv/bin/activate          # or: pip install -r requirements.txt
cp .env.example .env                              # fill in endpoint + keys
# put the raw dataset at data/raw/procurement_dataset/  (shared via Drive; not in Git)
make corpus                                       # rebuild ground truth, policies, synthetic docs, corpus v1
make test                                         # 84 tests
make up                                           # Postgres+pgvector and Langfuse (Docker)
```
Requires Python 3.11+, `pdftotext` (poppler-utils) and Docker.

## Repository layout
```
app/
  api/  agents/  tools/  retrieval/  ui/   Week 2-3 (empty packages)
  db/schema.sql                            vendors, documents, chunks (pgvector + full-text), reviews,
                                           conversation_turns, financial_metrics, append-only audit_events
  scoring/rubric.yaml, engine.py           deterministic rubric (becomes the compliance / financial tools)
  schemas.py                               Pydantic models for vendor facts and every copilot output
  llm_client.py                            the only way to call the LLM: token ledger, quota guard, JSON retry
data/
  raw/            NOT IN GIT: original downloads (~260 MB)
  manifests/      source register, CUAD/NDA selections, synthetic doc list, corpus_v1_manifest (frozen)
  ground_truth/   35 vendors, expected outcomes, document plan
  seed/           rows for the vendors and financial_metrics tables
  synthetic/      444 generated docs: policy/ contracts/ compliance_evidence/ performance_purchase_records/ adversarial/
  processed/      NOT IN GIT: corpus_v1.jsonl (make ingest)
  evaluation/     eval_v1 (step 1.5)
docs/             spec, decision log
scripts/          build_vendors, generate_policies, generate_synthetic_docs, ingest, retrieval_smoke_test, export_json_schemas
tests/            ground truth, corpus and schema guards
docker/           docker-compose (db, langfuse; api/ui stubs)
observability/    token ledger, traces (Week 2+)
```

## Data provenance
- **Real sources** (licences in `data/manifests/source_register.csv`):
  - Indian GFR 2017 and procurement manuals; DPDP Act 2023 and Rules 2025
  - UK Supplier Assurance Framework; World Bank procurement guidance
  - NIST SP 800-161r1; CSA CCM/CAIQ v4.1
  - CUAD, ContractNLI and ACORD; Common Paper standard agreements
- **Synthetic data:** the buyer (Indrapath Technologies Ltd), all 35 vendors, auditors, insurers, people and figures are fictional, and every vendor document is generated from `data/ground_truth/vendors.json`. Before any public demo, search each vendor name once to make sure it doesn't match a real company.

See `CONTRIBUTING.md` for branching, owners and rules.
