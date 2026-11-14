"""Step 2.3 reranker. A cross-encoder reads (query, passage) together and is much more precise than either retriever alone, which is
what the ACORD result (BM25 NDCG@5 = 0.07) motivates.

RAG_RERANKER=cross-encoder  BAAI/bge-reranker-base (or RAG_RERANKER_MODEL), CPU, via sentence-transformers; downloaded once from Hugging Face
RAG_RERANKER=lexical        offline fallback: query-term coverage + phrase match + vendor-name match (no download)
RAG_RERANKER=none           keep the fused order
If the cross-encoder cannot be loaded (no internet, no package) the reranker falls back to `lexical` and records why.
"""
from __future__ import annotations

import re

from app.rag.config import RagSettings, settings
from app.rag.index import Hit
from app.retrieval.chunking import tokenize


class Reranker:
    def __init__(self, cfg: RagSettings | None = None):
        self.cfg = cfg or settings()
        self.mode = self.cfg.reranker
        self.note = ""
        self.model = None
        if self.mode == "cross-encoder":
            try:
                from sentence_transformers import CrossEncoder
                self.model = CrossEncoder(self.cfg.reranker_model, max_length=512)
            except Exception as e:  # offline, missing package, etc.
                self.note = f"cross-encoder unavailable ({type(e).__name__}); using lexical reranker"
                self.mode = "lexical"

    def _lexical(self, query: str, h: Hit) -> float:
        qt = set(tokenize(query))
        if not qt:
            return 0.0
        ct = set(tokenize(h.chunk.text))
        cover = len(qt & ct) / len(qt)
        bigrams = {" ".join(p) for p in zip(tokenize(query), tokenize(query)[1:])}
        text = " ".join(tokenize(h.chunk.text))
        phrase = sum(1 for b in bigrams if b in text) / max(1, len(bigrams))
        num = set(re.findall(r"\d+(?:\.\d+)?", query))
        num_hit = len(num & set(re.findall(r"\d+(?:\.\d+)?", h.chunk.text))) / len(num) if num else 0.0
        return 0.6 * cover + 0.3 * phrase + 0.1 * num_hit

    def rerank(self, query: str, hits: list[Hit], top_k: int = 6) -> list[Hit]:
        if not hits or self.mode == "none":
            return hits[:top_k]
        if self.mode == "cross-encoder" and self.model is not None:
            scores = self.model.predict([(query, (h.chunk.parent_text or h.chunk.text)) for h in hits], batch_size=16, show_progress_bar=False)
            scores = [float(s) for s in scores]
        else:
            scores = [self._lexical(query, h) for h in hits]
        out = []
        for h, s in zip(hits, scores):
            pen = 0.5 if (self.cfg.demote_superseded and h.chunk.status != "CURRENT") else 1.0
            out.append(Hit(h.chunk, s * pen if s > 0 else s / pen if pen < 1 else s, "rerank"))
        out.sort(key=lambda h: -h.score)
        for i, h in enumerate(out, 1):
            h.rank = i
        return out[:top_k]
