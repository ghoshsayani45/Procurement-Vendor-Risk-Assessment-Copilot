# Week 2 RAG layer

New code only: `app/rag/`, `scripts/rag_*.py`, `tests/test_rag.py`, `Makefile.rag`, `.env.rag.example`, this file. No existing file is modified; the Week 1 baseline (`app/retrieval/`, `scripts/retrieval_baseline.py`, `docs/baselines.md`) stays exactly as frozen.

## What it covers (Track B requirements)
| Requirement | Where |
|---|---|
| Real corpus, 500–2,000 documents | corpus v1, 1,053 documents (`data/processed/corpus_v1.jsonl`) |
| Chunking experiments | `app/rag/chunking.py` (fixed, heading, clause, window) + `scripts/rag_chunking_experiments.py` |
| Hybrid retrieval (BM25 + dense) | `app/rag/index.py`, `app/rag/hybrid.py`: top-20 + top-20, reciprocal-rank fusion, dedupe |
| Reranker | `app/rag/reranker.py`: cross-encoder (`BAAI/bge-reranker-base`), lexical fallback |
| Citation-grounded answers | `app/rag/generator.py`: claims with source ids, uncited claims dropped, numbers checked against the cited text |
| Recall@k separate from answer quality | `app/rag/metrics.py`, `scripts/rag_retrieval_eval.py` (no LLM) vs `scripts/rag_eval_answers.py` (LLM + diagnosis) |

## Setup (5 minutes)
1. Copy the lines from `.env.rag.example` into `.env`. Set `EMBED_API_KEY` (the shared embedding key; it is **not** `LLM_API_KEY`) and `EMBED_CA_BUNDLE` (path to `vm02-ca.crt`).
   The existing `app.llm_client.embed()` sends `LLM_API_KEY` to the embedding server, so Week 2 uses its own client in `app/rag/embeddings.py`. Certificate checking stays on.
2. `python -m scripts.rag_check_embeddings` should print `OK: 2 vectors of 384 numbers`.
3. No `data/processed/corpus_v1.jsonl` yet? Put `data/raw/` in place and run `make ingest`.

## Workflow
```bash
python -m scripts.rag_chunking_experiments                 # step 2.2: compare 4 chunkers x 4 retrieval modes on the dev split
python -m scripts.rag_build_index --chunking heading       # save the winning index (change to the best strategy)
python -m scripts.rag_retrieval_eval --chunking heading    # recall@k by mode and category -> reports/rag_retrieval_eval.md
python -m scripts.rag_answer "What is Kestrion's auto-renewal notice period?"      # one question, with citations
python -m scripts.rag_eval_answers --chunking heading --limit 5                      # cheap smoke test of end-to-end answers
python -m scripts.rag_eval_answers --chunking heading --oracle                       # full dev run + oracle-context comparison
python -m scripts.grade reports/rag/answers_hybrid_rerank.jsonl --split dev          # the standard grader accepts the predictions
```
First embedding of the corpus is about 1,053 documents -> roughly 2,000-3,000 chunks -> about 150-200 requests of 16 texts. Vectors are cached in `data/processed/rag/embed_cache/`, so later runs are fast.

## Reading the results: retrieval vs answer quality
`rag_retrieval_eval` needs no LLM and reports hit@k, recall@k, MRR, nDCG@k and `quote@k` (share of gold quotes found verbatim inside the top-k chunks; this shows whether the chunker kept the evidence sentence intact).
`rag_eval_answers` gives every query a diagnosis:

| Diagnosis | Meaning | Fix |
|---|---|---|
| `retrieval_miss` / `retrieval_partial` | gold documents were not in the context the model saw | chunking, filters, fusion, reranker |
| `generator_miss` | all gold documents were in the context, but the answer lacks the fact | prompt, context size, deterministic tools |
| `citation_error` | right fact, wrong or no gold citation | citation rules, snippet selection |

`--oracle` additionally answers from the gold documents only. Retrieved-context score minus oracle score = cost of retrieval; oracle score minus 100% = cost of the 8B generator.

## Design choices (log as D18+ in docs/decisions.md after the team agrees)
- **D18** RAG uses its own embedding client with `EMBED_API_KEY` and the course CA file; the shared endpoint takes 16 texts per request, chunks are cut at 300 words (<512 tokens), bge queries get the instruction prefix, documents do not.
- **D19** Every chunk text starts with `[title | doc_id | date | status]` so look-alike synthetic vendors stay distinguishable.
- **D20** Vendor metadata filter (vendor's documents plus non-vendor documents such as policies) and a 0.5x penalty for SUPERSEDED chunks; both address the failure modes in `docs/baselines.md` and can be switched off (`RAG_VENDOR_FILTER=0`, `RAG_DEMOTE_SUPERSEDED=0`) for ablations.
- **D21** Retrieved text is untrusted: masked for personal data, flagged for instruction-like text and non-evidence document types, never executed.
- **D22** Evaluation scripts refuse the test split unless `--allow-test` is given (D12).

## Limits to be aware of
- Dense retrieval and the answer scripts need network access to the course servers; everything else and `tests/test_rag.py` run offline.
- The reranker model is downloaded from Hugging Face on first use (about 1 GB for `bge-reranker-base`). For a smaller download set `RAG_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`; without internet it falls back to the lexical reranker and says so in the output.
- Full reviews (`FULL_REVIEW`) need per-checklist-item retrieval plus the deterministic tools (Week 2/3); this layer targets question answering and evidence retrieval.
