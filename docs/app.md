# Week 3-4: application layer (API, database, UI, safety suite)

Built on branch `m6/4.x-api-ui-db` by Sounak Moulik. Everything runs offline; the course LLM is optional (`COPILOT_LLM`).

## Run it

| Way | Commands | Opens |
|---|---|---|
| Laptop, no Docker | `make ui` (API runs in-process, SQLite file `data/processed/copilot.sqlite`) | http://localhost:8501 |
| Laptop, API + UI separately | `make api` and, in a second terminal, `API_URL=http://localhost:8000 make ui` | API docs http://localhost:8000/docs |
| Docker | `cp .env.example .env` (fill it), then `make up` | UI :8501, API :8000, Langfuse :3000 |

`make load-db` creates the tables and loads vendors, financial metrics and document metadata (the API also does this on start-up). `make test` runs everything; `make test-safety` only the safety suite.

## API (`app/api/main.py`)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Status, database type, LLM mode, vendor count |
| `GET /v1/vendors`, `GET /v1/vendors/{id}` | Directory; profile and document inventory (no grading fields) |
| `POST /v1/requests` | Run the copilot; stores the request, response, conversation turns and audit events; returns `review_id` |
| `GET /v1/reviews`, `GET /v1/reviews/{id}` | History; one stored request with any human decision |
| `POST /v1/reviews/{id}/decision` | A named human approver records `APPROVED`, `REJECTED` or `MORE_INFO` |
| `GET /v1/reviews/{id}/audit` | Append-only audit trail |

Rate limit: `API_RATE_LIMIT` (default 30 requests a minute per client) on the two write endpoints.

**Decision rules (D29).** Only a full-review report can be decided; `decided_by` must be a full name (never `copilot`, `assistant`, `system`); `approver_role` must be one of the report's `required_approvers`; it must match the signed-in user (`X-User`); `APPROVED` or `REJECTED` is final, `MORE_INFO` leaves the review open. Every decision is an audit event with the approver's name and role.

## Database (`app/db/store.py`, `app/db/schema.sql`)
- `DATABASE_URL` = Postgres (docker compose) or unset = SQLite file. Same tables either way.
- `reviews` now holds every request (full reviews, comparisons, questions, refusals, clarifications): request, response, trace, and the human decision columns (D28). A database check refuses a decision without a named decider or by `copilot`.
- `audit_events` is append-only: Postgres rules (Day 0) and SQLite triggers block UPDATE and DELETE. Events: `REQUEST`, `TOOL_CALL`, `REFUSAL`, `CLARIFICATION`, `INJECTION_DETECTED`, `APPROVAL_DECLINED`, `PARTIAL_RESULT`, `RESPONSE`, `HUMAN_DECISION`.
- Reference data: 35 vendors, financial metrics, 444 document records (sha1 of text, access class). Chunks and embeddings stay in the Week 2 index until the embedding key is available.

## UI (`app/ui/streamlit_app.py`)
New request (full review, comparison, question) and a Reviews tab with history and the audit trail. A report shows tier, score, band (with the knockout that raised it), recommendation, checklist, findings with their source documents, conditions, and gaps; injection warnings and declined approvals are highlighted. The **approval panel** is the only place a decision is recorded. Without `API_URL` the UI starts the API in-process (D32).

## Tests
- `tests/test_api.py` (12): storage, audit trail, append-only enforcement, every decision guard, reference-data load.
- `tests/safety/test_safety.py` (55, M5): planted injections flagged with the band unchanged for 5 vendors; no review of any of the 35 vendors repeats personal data, leaks a prompt or key, or records a decision; the PII transcript is never repeated; email, press-release and "in progress" claims change nothing; 8 unsafe requests refused with an audit event; knockouts survive pressure; the spoofed policy draft is not applied.
- Full suite: 248 passed, 5 skipped (offline).

## Not yet done or verified
- **Postgres and Docker were not exercised here** (no Docker on the build machine); the SQLite path is fully tested. First `make up` should be checked by M6.
- `X-User` is a stand-in for single sign-on, not authentication (D30). Before any real deployment: SSO, and approver roles from a directory, not from the request.
- Role-based document access (`requester_role` vs `access_class`): all 444 synthetic documents are `internal`, so there is nothing to filter yet.
- Langfuse tracing of agent runs; chunks and embeddings in Postgres (pgvector).
