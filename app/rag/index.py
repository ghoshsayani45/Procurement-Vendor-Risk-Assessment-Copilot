"""HybridIndex: BM25 + dense vectors over the same chunks, with metadata filters. Saved under data/processed/rag/<strategy>/."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.rag.chunking import RagChunk, chunk_corpus, describe, load_corpus
from app.rag.config import RAG_DIR, RagSettings, settings
from app.rag.embeddings import get_embedder
from app.retrieval.chunking import tokenize   # reuse the Week 1 tokenizer so BM25 numbers stay comparable


@dataclass
class Hit:
    chunk: RagChunk
    score: float
    source: str = ""          # bm25 | dense | hybrid | rerank
    rank: int = 0


class HybridIndex:
    def __init__(self, chunks: list[RagChunk], vecs: np.ndarray | None, embedder=None, strategy: str = "heading"):
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self.vecs = vecs
        self.embedder = embedder
        self.strategy = strategy
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks])
        self._doc_rows: dict[str, list[int]] = {}
        for i, c in enumerate(chunks):
            self._doc_rows.setdefault(c.doc_id, []).append(i)

    # ---------------------------------------------------------------- build / load
    @classmethod
    def build(cls, strategy: str = "heading", docs: list[dict] | None = None, embedder=None, cfg: RagSettings | None = None,
              dense: bool = True, progress: bool = True, **chunk_kw) -> "HybridIndex":
        cfg = cfg or settings()
        docs = docs if docs is not None else load_corpus()
        chunks = chunk_corpus(docs, strategy, **chunk_kw)
        if progress:
            print(f"chunking={strategy}: {describe(chunks)}")
        vecs = None
        if dense:
            embedder = embedder or get_embedder(cfg)
            vecs = embedder.embed_texts([c.text for c in chunks], progress=progress)
        return cls(chunks, vecs, embedder, strategy)

    def save(self, name: str | None = None) -> Path:
        d = RAG_DIR / (name or self.strategy)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "chunks.jsonl", "w", encoding="utf-8") as fh:
            for c in self.chunks:
                fh.write(c.to_json() + "\n")
        if self.vecs is not None:
            np.save(d / "vectors.npy", self.vecs)
        (d / "meta.json").write_text(json.dumps(dict(strategy=self.strategy, chunks=len(self.chunks), dense=self.vecs is not None)), encoding="utf-8")
        return d

    @classmethod
    def load(cls, name: str = "heading", embedder=None, cfg: RagSettings | None = None) -> "HybridIndex":
        d = RAG_DIR / name
        if not (d / "chunks.jsonl").exists():
            raise FileNotFoundError(f"No saved index at {d}. Run: python -m scripts.rag_build_index --chunking {name}")
        with open(d / "chunks.jsonl", encoding="utf-8") as fh:
            chunks = [RagChunk(**json.loads(l)) for l in fh if l.strip()]
        vecs = np.load(d / "vectors.npy") if (d / "vectors.npy").exists() else None
        return cls(chunks, vecs, embedder or (get_embedder(cfg) if vecs is not None else None), name)

    # ---------------------------------------------------------------- filters
    def mask(self, vendor_ids: list[str] | None = None, doc_types: list[str] | None = None, allowed_access: set[str] | None = None,
             include_global: bool = True) -> np.ndarray | None:
        """Boolean mask over chunks. vendor filter keeps the vendor's own documents plus (include_global) non-vendor documents such as
        policies and regulations; it removes every *other* vendor's documents, the main source of look-alike false positives."""
        if not (vendor_ids or doc_types or allowed_access):
            return None
        m = np.ones(len(self.chunks), dtype=bool)
        for i, c in enumerate(self.chunks):
            if vendor_ids and c.vendor_id and c.vendor_id not in vendor_ids:
                m[i] = False
            if vendor_ids and not c.vendor_id and not include_global:
                m[i] = False
            if doc_types and c.doc_type not in doc_types:
                m[i] = False
            if allowed_access and c.access_class not in allowed_access:
                m[i] = False
        return m

    # ---------------------------------------------------------------- search
    def search_bm25(self, query: str, k: int = 20, mask: np.ndarray | None = None) -> list[Hit]:
        sc = self.bm25.get_scores(tokenize(query))
        if mask is not None:
            sc = np.where(mask, sc, -1e9)
        top = np.argsort(-sc)[:k]
        return [Hit(self.chunks[i], float(sc[i]), "bm25", r + 1) for r, i in enumerate(top) if sc[i] > -1e8]

    def search_dense(self, query: str, k: int = 20, mask: np.ndarray | None = None) -> list[Hit]:
        if self.vecs is None or self.embedder is None:
            raise RuntimeError("index has no dense vectors; build it without dense=False")
        sc = self.vecs @ self.embedder.embed_query(query)
        if mask is not None:
            sc = np.where(mask, sc, -1e9)
        top = np.argsort(-sc)[:k]
        return [Hit(self.chunks[i], float(sc[i]), "dense", r + 1) for r, i in enumerate(top) if sc[i] > -1e8]
