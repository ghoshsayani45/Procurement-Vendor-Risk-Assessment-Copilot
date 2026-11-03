# Contributing

1. Branch from `main`: `git checkout -b <member>/<step>-<short-name>` (e.g. `m2/1.4-ingestion`).
2. Keep PRs small; one step or one tool per PR. Fill in the PR template.
3. `make test` must pass. Rubric or ground-truth changes need a line in `docs/decisions.md`.
4. Never commit `.env`, anything under `data/raw/` or `data/processed/`, or real vendor records.
5. Every LLM call goes through `app/llm_client.py` so tokens are logged and the quota guard applies.
6. After the Week 1 gate, `data/evaluation/eval_v1.jsonl` is read-only. Fixes go into `eval_v2` with a note.

## Owners (from the responsibility matrix)
| Member | Area | Main folders |
|---|---|---|
| M1 | Product & evaluation | `docs/`, `data/evaluation/`, `data/ground_truth/` |
| M2 | Data & retrieval | `scripts/ingest.py`, `app/retrieval/`, `data/manifests/` |
| M3 | Agents & tools | `app/agents/`, `app/tools/`, `app/scoring/` |
| M4 | Frontend & UX | `app/ui/` |
| M5 | Safety & observability | `observability/`, `tests/safety/` |
| M6 | Platform & delivery | `app/api/`, `app/db/`, `docker/`, `Makefile` |
