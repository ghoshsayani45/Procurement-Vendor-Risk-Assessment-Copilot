"""Build and save a hybrid (BM25 + dense) index.

    python -m scripts.rag_build_index --chunking heading
    python -m scripts.rag_build_index --chunking clause --no-dense      # BM25 only, no endpoint needed
    python -m scripts.rag_build_index --corpus synthetic --chunking heading   # offline smoke test on data/synthetic only

Output: data/processed/rag/<chunking>/{chunks.jsonl, vectors.npy}. Embeddings are cached, so re-running is cheap.
"""
import argparse
import time

from app.rag.chunking import STRATEGIES
from app.rag.evalkit import load_docs
from app.rag.index import HybridIndex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunking", default="heading", choices=STRATEGIES)
    ap.add_argument("--corpus", default="corpus", choices=["corpus", "synthetic"])
    ap.add_argument("--no-dense", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    docs = load_docs(a.corpus)
    idx = HybridIndex.build(a.chunking, docs=docs, dense=not a.no_dense)
    path = idx.save(a.chunking if a.corpus == "corpus" else f"{a.chunking}_synthetic")
    print(f"saved {len(idx.chunks)} chunks from {len(docs)} documents to {path} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
