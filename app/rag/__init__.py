"""Week 2 RAG layer (new package; the Week 1 baseline in app/retrieval/ is untouched).

    chunking.py    fixed / heading-aware / clause-aware / sentence-window strategies, with metadata
    embeddings.py  client for the shared bge-small-en-v1.5 endpoint (own key + CA cert, 16 texts per request, disk cache)
    index.py       HybridIndex: BM25 + dense vectors + metadata filters, saved under data/processed/rag/
    hybrid.py      reciprocal-rank fusion, vendor/status filtering, dedupe
    reranker.py    cross-encoder reranker with a lexical fallback
    generator.py   citation-grounded answer generation + validation
    pipeline.py    RagPipeline: retrieve -> fuse -> rerank -> answer
    metrics.py     retrieval metrics (recall@k, hit@k, MRR, nDCG, quote coverage) and answer metrics, kept separate
"""
