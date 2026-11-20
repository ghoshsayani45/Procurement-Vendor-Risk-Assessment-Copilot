# Procurement & Vendor Risk Assessment Copilot

A Track B capstone (Executive PG Programme in Generative AI and Agentic AI). It is a multi-agent copilot that assesses technology vendors for onboarding and renewal, built on a hosted ≤8B model. It retrieves cited evidence, applies a deterministic risk rubric, and routes every decision to a human approver.

**Full project documentation (12 pages, Weeks 1-4, architecture, results, challenges):** [docs/Project_Documentation.pdf](docs/Project_Documentation.pdf)

## Status
| Week 1 step | Status | Where |
|---|---|---|
| Day 0 setup | Done (endpoint values still to fill in `.env`) | `.env.example`, `app/llm_client.py`, `docker/`, `app/db/schema.sql` |
| 1.1 Task specification | Done; decisions D1–D15 need team sign-off | `docs/spec.md`, `docs/decisions.md` |
| 1.2 Rubric and schemas | Done | `app/scoring/`, `app/schemas.py`, `schemas/` |
| 1.3 Synthetic vendor set | Done (35 vendors) | `data/ground_truth/` |
| 1.4 Corpus | Done; **corpus v1 frozen: 1,053 documents** | `data/synthetic/`, `data/manifests/`, `scripts/ingest.py` |
| 1.5 Evaluation set | Done; **eval_v1 frozen: 80 queries (30 dev / 50 test)**, with grader | `data/evaluation/`, `scripts/grade.py` |
| 1.6–1.7 Prompting baseline + failure log | Done (Qwen3-8B, dev split: 50–53%) | `app/prompting.py`, `app/failure_analysis.py`, `docs/failure_log.md` |
| 1.8 Retrieval baselines | **BM25 done** (hit@10 dev 0.89 / test 0.95; ACORD NDCG@5 0.07); dense waits for the embeddings endpoint | `docs/baselines.md`, `reports/retrieval_baseline_v1.json` |
| 2.2–2.4 RAG layer | Done (code); real run needs corpus v1 + embedding key | `app/rag/`, `docs/rag.md` |
| 3.x Tools and agents | Done (code); **dev split 26/30 offline**, full reviews 7/7 | `app/tools/`, `app/agents/`, `docs/agents.md` |
| 4 App layer | Done (code): FastAPI, database with append-only audit, Streamlit approval UI, safety suite; Docker not yet run | `app/api/`, `app/db/`, `app/ui/`, `tests/safety/`, `docs/app.md` |

## Quick start
**New teammate? Follow [INSTALL.md](INSTALL.md)** (PDF: [docs/Installation_and_Running_Guide.pdf](docs/Installation_and_Running_Guide.pdf)) (Windows, macOS, Linux; one-command start with `run_app.bat` / `run_app.sh`). The commands below are the Makefile route.

```bash
git clone <repo> && cd procurement-vendor-risk-copilot
make setup && source .venv/bin/activate          # or: pip install -r requirements.txt
cp .env.example .env                              # fill in endpoint + keys
# put the raw dataset at data/raw/procurement_dataset/  (shared via Drive; not in Git)
make corpus                                       # rebuild ground truth, policies, synthetic docs, corpus v1
make test                                         # 248 tests (offline)
make ui                                           # reviewer UI on :8501 (API in-process, SQLite)
make up                                           # Postgres+pgvector and Langfuse (Docker)
```
Requires Python 3.11+, `pdftotext` (poppler-utils) and Docker.

## Repository layout
```
app/
  agents/  tools/                          Week 3: router/planner/executor/writer/critic (LangGraph) and the 5 tools
  rag/                                     Week 2: chunking, hybrid retrieval, reranker, cited answers
  api/  ui/  db/store.py                    Week 4: FastAPI service, Streamlit reviewer UI with approval panel, persistence
  db/schema.sql                            vendors, documents, chunks (pgvector + full-text), reviews,
                                           conversation_turns, financial_metrics, append-only audit_events
  scoring/rubric.yaml, engine.py           deterministic rubric (becomes the compliance / financial tools)
  schemas.py                               Pydantic models for vendor facts and every copilot output
  llm_client.py                            the only way to call the LLM: token ledger, quota guard, JSON retry, mock backend
  prompting.py, failure_analysis.py        step 1.6 strategies and step 1.7 failure classifier
  retrieval/chunking.py, retrievers.py     fixed-512 chunker, BM25 and dense retrievers
data/
  raw/            NOT IN GIT: original downloads (~260 MB)
  manifests/      source register, CUAD/NDA selections, synthetic doc list, corpus_v1_manifest (frozen)
  ground_truth/   35 vendors, expected outcomes, document plan
  seed/           rows for the vendors and financial_metrics tables
  synthetic/      444 generated docs: policy/ contracts/ compliance_evidence/ performance_purchase_records/ adversarial/
  processed/      NOT IN GIT: corpus_v1.jsonl (make ingest)
  evaluation/     eval_v1.jsonl (80 queries, frozen), sha256, README, CHANGELOG
docs/             spec, decision log
scripts/          build_vendors, generate_policies, generate_synthetic_docs, ingest, retrieval_smoke_test,
                  build_eval_set, grade, retrieval_baseline, prompt_baseline, export_json_schemas
tests/            ground truth, corpus, eval set, grader and baseline guards (96 tests)
reports/          baseline results (JSON); runs/ holds raw LLM outputs (not in Git)
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
