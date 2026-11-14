"""Step 2.2 chunking experiments. For each chunking strategy build the index and measure retrieval on the dev queries
(document-level recall@k / hit@k / MRR and gold-quote coverage) for BM25, dense, hybrid and hybrid+rerank.

    python -m scripts.rag_chunking_experiments --strategies fixed,heading,clause,window
    python -m scripts.rag_chunking_experiments --no-dense --strategies fixed,heading,clause   # no endpoint needed

Writes reports/rag_chunking_experiments.json and reports/rag_chunking_experiments.md (new files; docs/baselines.md is not touched).
"""
import argparse
import json
import time

from app.rag.chunking import describe
from app.rag.config import REPORTS, settings
from app.rag.embeddings import get_embedder
from app.rag.evalkit import load_docs, load_queries
from app.rag.index import HybridIndex
from app.rag.metrics import retrieval_row, summarise
from app.rag.pipeline import RagPipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default="fixed,heading,clause,window")
    ap.add_argument("--corpus", default="corpus", choices=["corpus", "synthetic"])
    ap.add_argument("--split", default="dev")
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--no-vendor-filter", action="store_true")
    a = ap.parse_args()
    cfg = settings()
    cfg.vendor_filter = not a.no_vendor_filter
    docs = load_docs(a.corpus)
    queries = load_queries(a.split, a.allow_test, {d["doc_id"] for d in docs})
    print(f"{len(docs)} documents, {len(queries)} {a.split} queries with gold documents present")
    embedder = None if a.no_dense else get_embedder(cfg)
    modes = ["bm25"] + ([] if a.no_dense else ["dense", "hybrid"]) + ([] if (a.no_dense or a.no_rerank) else ["hybrid+rerank"])
    report = dict(run_at=time.strftime("%Y-%m-%d %H:%M"), split=a.split, corpus=a.corpus, vendor_filter=cfg.vendor_filter, results={})
    for strat in a.strategies.split(","):
        idx = HybridIndex.build(strat, docs=docs, embedder=embedder, cfg=cfg, dense=not a.no_dense, progress=False)
        pipe = RagPipeline(idx, cfg)
        entry = dict(chunking=describe(idx.chunks), modes={})
        for mode in modes:
            rows = []
            for q in queries:
                ret = pipe.retrieve(q["request"]["question"], vendor_ids=q["request"]["vendor_ids"] or None, mode=mode, k=20)
                final = ret.final
                row = retrieval_row(final, q["gold_doc_ids"], q["gold_quotes"], ks=(1, 3, 5, 6, 10, 20))
                row.update(id=q["id"], category=q["category"], split=q["split"], latency_ms=ret.ms)
                rows.append(row)
            entry["modes"][mode] = dict(summary=summarise(rows), per_query=rows)
            m = entry["modes"][mode]["summary"]["ALL"]
            print(f"{strat:8s} {mode:14s} hit@5={m.get('hit@5')} recall@5={m.get('recall@5')} recall@10={m.get('recall@10')} mrr={m['mrr']} quote@5={m.get('quote@5')}")
        report["results"][strat] = entry
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "rag_chunking_experiments.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    lines = ["# RAG chunking experiments (step 2.2)", "", f"Run {report['run_at']} · split `{a.split}` · corpus `{a.corpus}` · vendor filter {'on' if cfg.vendor_filter else 'off'}", "",
             "| Chunking | Chunks | Median words | Mode | hit@5 | recall@5 | recall@10 | MRR | quote@5 |", "|---|---|---|---|---|---|---|---|---|"]
    for strat, e in report["results"].items():
        for mode, r in e["modes"].items():
            m = r["summary"]["ALL"]
            lines.append(f"| {strat} | {e['chunking']['chunks']} | {e['chunking']['median_words']} | {mode} | {m.get('hit@5')} | {m.get('recall@5')} | {m.get('recall@10')} | {m['mrr']} | {m.get('quote@5')} |")
    (REPORTS / "rag_chunking_experiments.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote reports/rag_chunking_experiments.{json,md}")


if __name__ == "__main__":
    main()
