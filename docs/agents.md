# Week 3: tools and agents

Code: `app/tools/` (evidence register, document store, safety scanner, five tools) and `app/agents/` (router, planner, executor, writer, critic, LangGraph graph). Entry point: `app.agents.copilot.run(request)`. Tests: `tests/test_agents.py` (offline). Evaluation: `make copilot-dev` (= `python -m scripts.run_copilot`).

## Architecture

```
request ─► route ──refuse / clarify──────────────────────────────► critic ─► response
             │                                                       ▲
             └─run─► plan ─► execute (≤10 tool calls, 1 retry) ─► write
                      │          │
                      │          ├─ vendor_search             register + document inventory
                      │          ├─ compliance_checker        rubric engine: tier, checklist, findings, score, band, approvers
                      │          ├─ financial_risk_calculator ratios vs policy thresholds
                      │          ├─ vendor_compare            same-group check, ranking
                      │          └─ document_search           Week 2 hybrid/BM25 retrieval + vendor-document safety scan
                      └─ templates: new_vendor_full · renewal_full · comparison · single_question
```

| Node | What it does | LLM? |
|---|---|---|
| route | Refusal categories (spec 6), clarification (unknown / ambiguous vendor, cross-group or single-vendor comparison), mixed requests (answer + decline the approval) | No |
| plan | Fixed template per request kind, validated as `Plan` (≤ 6 steps) | No |
| execute | Runs tools; one retry; 10-call cap; failures and the cap become `PARTIAL` with `partial_reason` | No |
| write | `Report` / `ComparisonResult` copied from tool output; `Answer` from structured records when the question maps to a known field, otherwise retrieval + the Week 2 cited generator (or an extractive fallback with no LLM) | Optional: report summary; open questions |
| critic | Schema validation; repairs tier/score/band/recommendation/approvers to the engine values; drops uncited or invented findings; clears any human decision; ensures injections are reported; masks PII | No |

Audit events (refusal, clarification, injection detected, approval declined, partial result) go to `observability/audit_events.jsonl` (git-ignored) until the API writes them to the `audit_events` table.

## Where the facts come from (D23)
Tools read the **evidence register** (`app/tools/register.py`): `data/ground_truth/vendors.json` with the answer fields (`planted_issues`, `traps`, `adversarial`, `notes`) removed. It stands in for the GRC/procurement system of record: certificate dates, contract clauses, ratios, performance figures, debarment and COI register entries. Every fact keeps the id of the document that carries it, so findings cite documents. Document front matter is stripped of the same answer fields (`app/tools/documents.py`). Tests check that no answer field reaches any tool.

## Dev-split results (2026-11-14, `--llm none`, no model calls)

| Metric | Week 1 best single prompt (gold docs pasted in) | Week 3 copilot |
|---|---|---|
| Accuracy | 0.533 (CoT-SC) | **0.867** (26/30) |
| Full reviews | 0/7 | **7/7** |
| Comparisons | 0/2 | **2/2** |
| Band / recommendation / checklist | 0.43 / 0.57 / 0.85 | **1.0 / 1.0 / 1.0** |
| Finding recall | 0.14 | **1.0** (precision 1.0) |
| Injection resistance | 0.0 | **1.0** |
| Refusals / clarifications | 3/3 / 2/2 | 3/3 / 2/2 |
| Tool calls per query · median latency | – · 1.9–12 s | 2.3 · 22 ms |

Remaining failures: EVAL-056/058/059 (external regulation) need the real DPDP and GFR texts, which are in corpus v1 (`make ingest` with `data/raw/`), not in the synthetic-only store on this machine; EVAL-049 (approvers for a hypothetical renewal) needs reasoning over the delegation policy, which is the LLM path (`--llm endpoint`).

**Caveats.** The full-review numbers are high by construction: scores come from the same deterministic engine that produced the ground truth, so they test that the agent calls the right tools and passes their output through intact, not the engine itself. The test split has not been run (D12); it is for the Week 3 gate.

## Next steps
1. Build corpus v1 and the Week 2 index, then `make copilot-dev LLM=endpoint` for the open-question path.
2. Week 3 gate: one test-split run (`--split test --allow-test`), recorded in `docs/baselines.md`.
3. Role-based access (`access_class` filter by `requester_role`), PII masking of names (regex covers emails, phone, Aadhaar, PAN).
4. `app/api` (FastAPI) and `app/ui` (Streamlit approval panel) on top of `copilot.run`; audit events to Postgres.
