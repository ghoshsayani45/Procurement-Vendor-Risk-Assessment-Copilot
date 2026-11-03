"""Week 1 baseline retrievers: BM25 (sparse) and dense (embeddings). Hybrid + reranker arrive in Week 2 (step 2.3).

Dense embeddings come from, in order of preference:
  1. the course embeddings endpoint, via app.llm_client.embed   (EMBED_BACKEND=endpoint, the default)
  2. a local sentence-transformers model on a team laptop        (EMBED_BACKEND=local, EMBED_LOCAL_MODEL=BAAI/bge-small-en-v1.5)
Vectors are cached in data/processed/embeddings/<backend>_<model>.npy so the corpus is embedded once.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from app.retrieval.chunking import ROOT, Chunk, tokenize

CACHE = ROOT / "data" / "processed" / "embeddings"


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[Chunk], k1: float = 1.2, b: float = 0.75):
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks], k1=k1, b=b)

    def search(self, query: str, k: int = 20) -> list[tuple[Chunk, float]]:
        scores = self.bm25.get_scores(tokenize(query))
        top = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in top]


def _embedder():
    backend = os.getenv("EMBED_BACKEND", "endpoint")
    if backend == "local":
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("EMBED_LOCAL_MODEL", "BAAI/bge-small-en-v1.5")
        m = SentenceTransformer(model_name)
        return f"local_{model_name}", lambda texts: m.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    from app.llm_client import embed
    model_name = os.environ["EMBED_MODEL"]
    return f"endpoint_{model_name}", lambda texts: np.array(embed(texts, tag="retrieval_baseline"))


class DenseRetriever:
    name = "dense"

    def __init__(self, chunks: list[Chunk], batch: int = 64):
        self.chunks = chunks
        self.model_id, self.encode = _embedder()
        key = hashlib.sha1(("|".join(c.chunk_id for c in chunks) + self.model_id).encode()).hexdigest()[:12]
        path = CACHE / f"{self.model_id.replace('/', '_')}_{key}.npy"
        if path.exists():
            self.vecs = np.load(path)
        else:
            parts = [np.asarray(self.encode([c.text for c in chunks[i:i + batch]]), dtype=np.float32) for i in range(0, len(chunks), batch)]
            self.vecs = np.vstack(parts)
            CACHE.mkdir(parents=True, exist_ok=True)
            np.save(path, self.vecs)
        self.vecs = self.vecs / (np.linalg.norm(self.vecs, axis=1, keepdims=True) + 1e-12)

    def search(self, query: str, k: int = 20) -> list[tuple[Chunk, float]]:
        q = np.asarray(self.encode([query]), dtype=np.float32)[0]
        q = q / (np.linalg.norm(q) + 1e-12)
        scores = self.vecs @ q
        top = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in top]
