"""Shared helpers for the RAG evaluation scripts."""
from __future__ import annotations

import json
import sys

from app.rag.chunking import load_corpus, load_markdown_corpus
from app.rag.config import CORPUS_PATH, ROOT

EVAL = ROOT / "data" / "evaluation" / "eval_v1.jsonl"


def load_docs(source: str = "corpus") -> list[dict]:
    """corpus = data/processed/corpus_v1.jsonl (the frozen 1,053 docs); synthetic = only data/synthetic/*.md (offline smoke test)."""
    if source == "synthetic":
        print("NOTE: using synthetic documents only; numbers are NOT comparable with the Week 1 baseline.", file=sys.stderr)
        return load_markdown_corpus()
    return load_corpus(CORPUS_PATH)


def load_queries(split: str = "dev", allow_test: bool = False, doc_ids: set[str] | None = None, categories: set[str] | None = None,
                 need_gold: bool = True) -> list[dict]:
    """Read eval_v1 (read-only). The test split is refused unless allow_test=True (decision D12: test runs only at the Week 3/4 gates)."""
    if split in ("test", "all") and not allow_test:
        raise SystemExit("Refusing to use the test split (decision D12). Use --split dev, or pass --allow-test at an official gate.")
    qs = [json.loads(l) for l in open(EVAL, encoding="utf-8") if l.strip()]
    qs = [q for q in qs if split == "all" or q["split"] == split]
    if need_gold:
        qs = [q for q in qs if q["gold_doc_ids"]]
    if categories:
        qs = [q for q in qs if q["category"] in categories]
    if doc_ids is not None:                          # keep only queries whose gold docs exist in the loaded corpus
        qs = [q for q in qs if set(q["gold_doc_ids"]) <= doc_ids]
    return qs
