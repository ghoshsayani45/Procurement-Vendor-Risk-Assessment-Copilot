"""RagPipeline: vendor detection -> hybrid candidates -> rerank -> citation-grounded answer, with a stage-by-stage trace so retrieval
can be measured separately from generation."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.rag.config import RagSettings, settings
from app.rag.hybrid import detect_vendors, hybrid_search, load_vendors
from app.rag.index import Hit, HybridIndex
from app.rag.reranker import Reranker

MODES = ("bm25", "dense", "hybrid", "hybrid+rerank")


@dataclass
class Retrieval:
    query: str
    mode: str
    vendor_ids: list[str]
    candidates: list[Hit]        # before reranking (what recall@20 is measured on)
    final: list[Hit]             # what the generator sees
    ms: float = 0.0
    note: str = ""


class RagPipeline:
    def __init__(self, index: HybridIndex, cfg: RagSettings | None = None, reranker: Reranker | None = None):
        self.index = index
        self.cfg = cfg or settings()
        self._reranker = reranker
        self.vendors = load_vendors()

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker(self.cfg)
        return self._reranker

    def retrieve(self, query: str, *, vendor_ids: list[str] | None = None, mode: str = "hybrid+rerank", k: int | None = None) -> Retrieval:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        k = k or self.cfg.final_k
        t0 = time.time()
        vids = vendor_ids if vendor_ids else detect_vendors(query, self.vendors)
        base = "hybrid" if mode.startswith("hybrid") else mode
        cands = hybrid_search(self.index, query, vendor_ids=vids or None, cfg=self.cfg, mode=base)
        note = ""
        if mode == "hybrid+rerank":
            final = self.reranker.rerank(query, cands, top_k=max(k, 1))
            note = self.reranker.note
        else:
            final = cands[:k]
        return Retrieval(query, mode, vids, cands, final, round((time.time() - t0) * 1000, 1), note)

    def answer(self, question: str, *, vendor_ids: list[str] | None = None, as_of: str = "2026-11-01", mode: str = "hybrid+rerank", k: int | None = None):
        from app.rag.generator import generate
        r = self.retrieve(question, vendor_ids=vendor_ids, mode=mode, k=k)
        return r, generate(question, r.final, as_of=as_of, cfg=self.cfg)
