"""Hybrid fusion: top-N BM25 + top-N dense -> reciprocal-rank fusion -> dedupe -> (reranker lives in reranker.py).

Retrieval configuration from the project plan: top-20 BM25 and top-20 dense candidates, fused, deduplicated by document and clause,
reranked to the top 6 passages. Vendor metadata filtering and 'latest version wins' demotion address the two failure modes named in
docs/baselines.md (look-alike vendor documents; the superseded 2022 manual outranking the current one).
"""
from __future__ import annotations

import re

from app.rag.config import RagSettings, settings
from app.rag.index import Hit, HybridIndex

_STATUS_PENALTY = 0.5     # multiplier on the fused score of SUPERSEDED / DRAFT chunks


def rrf(rank_lists: list[list[Hit]], k: int = 60, weights: list[float] | None = None) -> list[Hit]:
    """Reciprocal Rank Fusion: score = sum_w w / (k + rank). Rank-based, so BM25 and cosine scales never need calibrating."""
    weights = weights or [1.0] * len(rank_lists)
    acc: dict[str, float] = {}
    keep: dict[str, Hit] = {}
    for lst, w in zip(rank_lists, weights):
        for r, h in enumerate(lst, 1):
            acc[h.chunk.chunk_id] = acc.get(h.chunk.chunk_id, 0.0) + w / (k + r)
            keep.setdefault(h.chunk.chunk_id, h)
    out = [Hit(keep[cid].chunk, s, "hybrid") for cid, s in acc.items()]
    out.sort(key=lambda h: -h.score)
    for i, h in enumerate(out, 1):
        h.rank = i
    return out


def detect_vendors(query: str, vendors: list[dict]) -> list[str]:
    """Find vendor ids named in a question ('Quillmoor', 'Kestrion', 'V009'). `vendors` rows come from data/seed/vendors.csv."""
    q = query.lower()
    found = []
    for v in vendors:
        first = re.split(r"\s+", v["name"])[0].lower()
        if re.search(rf"\b{re.escape(v['id'].lower())}\b", q) or (len(first) > 3 and re.search(rf"\b{re.escape(first)}", q)):
            found.append(v["id"])
    return found


def load_vendors() -> list[dict]:
    import csv
    from app.rag.config import ROOT
    p = ROOT / "data" / "seed" / "vendors.csv"
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def dedupe(hits: list[Hit], per_doc: int = 2, per_section: int = 1) -> list[Hit]:
    """Keep at most `per_doc` chunks per document and `per_section` per (document, section), preserving rank order."""
    seen_doc: dict[str, int] = {}
    seen_sec: dict[tuple, int] = {}
    out = []
    for h in hits:
        c = h.chunk
        if seen_doc.get(c.doc_id, 0) >= per_doc or seen_sec.get((c.doc_id, c.section), 0) >= per_section and c.section:
            continue
        seen_doc[c.doc_id] = seen_doc.get(c.doc_id, 0) + 1
        seen_sec[(c.doc_id, c.section)] = seen_sec.get((c.doc_id, c.section), 0) + 1
        out.append(h)
    return out


def hybrid_search(index: HybridIndex, query: str, *, vendor_ids: list[str] | None = None, cfg: RagSettings | None = None,
                  candidates: int | None = None, mode: str = "hybrid", allowed_access: set[str] | None = None,
                  include_global: bool = True) -> list[Hit]:
    """Candidate generation. mode = bm25 | dense | hybrid. Returns a fused, filtered list of candidates (not yet reranked)."""
    cfg = cfg or settings()
    mask = index.mask(vendor_ids if cfg.vendor_filter else None, allowed_access=allowed_access, include_global=include_global)
    lists = []
    if mode in ("bm25", "hybrid"):
        lists.append(index.search_bm25(query, cfg.top_bm25, mask))
    if mode in ("dense", "hybrid"):
        lists.append(index.search_dense(query, cfg.top_dense, mask))
    fused = lists[0] if len(lists) == 1 else rrf(lists, cfg.rrf_k)
    if cfg.demote_superseded:
        for h in fused:
            if h.chunk.status != "CURRENT":
                h.score *= _STATUS_PENALTY
        fused.sort(key=lambda h: -h.score)
    fused = fused[:candidates] if candidates else fused
    for i, h in enumerate(fused, 1):
        h.rank = i
    return fused
