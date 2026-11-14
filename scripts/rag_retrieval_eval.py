"""Retrieval-only evaluation (no LLM). Reports recall@k per mode and per category, separately from answer quality.

    python -m scripts.rag_retrieval_eval --chunking heading --modes bm25,dense,hybrid,hybrid+rerank
Compare with the Week 1 BM25 baseline (dev hit@10 0.89, recall@10 0.68, MRR 0.71) in docs/baselines.md.
Writes reports/rag_retrieval_eval.json and .md.
"""
import argparse
import json
import time

from app.rag.config import REPORTS, settings
from app.rag.evalkit import load_docs, load_queries
from app.rag.index import HybridIndex
from app.rag.metrics import retrieval_row, summarise
from app.rag.pipeline import RagPipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunking", default=None)
    ap.add_argument("--modes", default="bm25,dense,hybrid,hybrid+rerank")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--corpus", default="corpus", choices=["corpus", "synthetic"])
    ap.add_argument("--no-vendor-filter", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the index instead of loading the saved one")
    a = ap.parse_args()
    cfg = settings()
    cfg.vendor_filter = not a.no_vendor_filter
    strat = a.chunking or cfg.chunking
    if a.rebuild or a.corpus == "synthetic":
        idx = HybridIndex.build(strat, docs=load_docs(a.corpus), cfg=cfg, dense="dense" in a.modes or "hybrid" in a.modes)
    else:
        idx = HybridIndex.load(strat, cfg=cfg)
    queries = load_queries(a.split, a.allow_test, {c.doc_id for c in idx.chunks})
    pipe = RagPipeline(idx, cfg)
    report = dict(run_at=time.strftime("%Y-%m-%d %H:%M"), chunking=strat, split=a.split, queries=len(queries), vendor_filter=cfg.vendor_filter, modes={})
    for mode in a.modes.split(","):
        rows = []
        for q in queries:
            ret = pipe.retrieve(q["request"]["question"], vendor_ids=q["request"]["vendor_ids"] or None, mode=mode, k=20)   # same depth for every mode so recall@10 is comparable
            row = retrieval_row(ret.final, q["gold_doc_ids"], q["gold_quotes"])
            row.update(id=q["id"], category=q["category"], split=q["split"], latency_ms=ret.ms, top3=[h.chunk.doc_id for h in ret.final[:3]],
                       candidate_recall=retrieval_row(ret.candidates, q["gold_doc_ids"], None, ks=(20,)).get("recall@20"))
            rows.append(row)
        s = summarise(rows)
        report["modes"][mode] = dict(summary=s, per_query=rows, worst=sorted([r for r in rows if r["category"] != "full_review"], key=lambda r: (r["mrr"], r["recall@10"]))[:8])
        m = s["ALL"]
        print(f"{mode:14s} n={m['n']} hit@5={m.get('hit@5')} hit@10={m.get('hit@10')} recall@5={m.get('recall@5')} recall@10={m.get('recall@10')} mrr={m['mrr']} quote@6={m.get('quote@6')}")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "rag_retrieval_eval.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    cats = sorted({r["category"] for r in next(iter(report["modes"].values()))["per_query"]})
    md = [f"# RAG retrieval evaluation", "", f"{report['run_at']} · chunking `{strat}` · split `{a.split}` · {len(queries)} queries · vendor filter {'on' if cfg.vendor_filter else 'off'}", "",
          "| Mode | hit@5 | hit@10 | recall@5 | recall@10 | MRR | nDCG@10 | quote@6 | median ms |", "|---|---|---|---|---|---|---|---|---|"]
    for mode, r in report["modes"].items():
        m = r["summary"]["ALL"]
        md.append(f"| {mode} | {m.get('hit@5')} | {m.get('hit@10')} | {m.get('recall@5')} | {m.get('recall@10')} | {m['mrr']} | {m.get('ndcg@10')} | {m.get('quote@6')} | {m['median_latency_ms']} |")
    md += ["", "## recall@10 by category", "", "| Category | " + " | ".join(report["modes"]) + " |", "|---|" + "---|" * len(report["modes"])]
    for c in cats:
        md.append(f"| {c} | " + " | ".join(str(r["summary"].get(c, {}).get("recall@10", "")) for r in report["modes"].values()) + " |")
    (REPORTS / "rag_retrieval_eval.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wrote reports/rag_retrieval_eval.{json,md}")


if __name__ == "__main__":
    main()
