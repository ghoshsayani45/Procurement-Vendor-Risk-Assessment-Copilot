"""End-to-end answer quality, reported SEPARATELY from retrieval recall, with a per-query diagnosis.

    python -m scripts.rag_eval_answers --chunking heading --mode hybrid+rerank --limit 10     # smoke test
    python -m scripts.rag_eval_answers --chunking heading --mode hybrid+rerank --oracle       # also run with gold documents as context

For every question-type dev query (lookup, policy, regulation, missing/conflicting evidence) it records:
  retrieval  : hit / recall of gold documents in the context the model saw
  answer     : fact recall, gold document cited, citation precision
  diagnosis  : retrieval_miss | retrieval_partial | generator_miss | citation_error | ok
With --oracle it also answers from the gold documents only (as in the Week 1 prompting baseline). The gap between the retrieved-context run
and the oracle run is the cost of retrieval; the gap between the oracle run and 100% is the cost of the weak generator.
Predictions are written in the format scripts.grade expects: reports/rag/answers_<mode>.jsonl
"""
import argparse
import json
import time
from collections import Counter

from app.rag.config import REPORTS, settings
from app.rag.evalkit import load_queries
from app.rag.generator import generate
from app.rag.index import Hit, HybridIndex
from app.rag.metrics import answer_row, retrieval_row
from app.rag.pipeline import RagPipeline

QA = {"lookup_vendor", "internal_policy", "external_regulation", "missing_conflicting_evidence"}


def gold_hits(index: HybridIndex, gold_docs: list[str]) -> list[Hit]:
    out = []
    for d in gold_docs:
        for i in index._doc_rows.get(d, [])[:2]:
            out.append(Hit(index.chunks[i], 1.0, "oracle"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunking", default=None)
    ap.add_argument("--mode", default="hybrid+rerank")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--categories", default=",".join(sorted(QA)))
    a = ap.parse_args()
    cfg = settings()
    idx = HybridIndex.load(a.chunking or cfg.chunking, cfg=cfg)
    pipe = RagPipeline(idx, cfg)
    queries = load_queries(a.split, a.allow_test, {c.doc_id for c in idx.chunks}, set(a.categories.split(",")))
    if a.limit:
        queries = queries[:a.limit]
    print(f"{len(queries)} queries · {a.mode} · chunking {idx.strategy}")
    out_dir = REPORTS / "rag"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, preds = [], []
    for q in queries:
        qn = q["request"]["question"]
        ret, ans = pipe.answer(qn, vendor_ids=q["request"]["vendor_ids"] or None, as_of=q["request"]["as_of"], mode=a.mode)
        ctx_docs = list(dict.fromkeys(c.split("#")[0] for c in ans.context_chunks))
        row = dict(id=q["id"], category=q["category"], mode=a.mode)
        row["retrieval"] = retrieval_row(ret.final, q["gold_doc_ids"], q["gold_quotes"], ks=(6,))
        row["answer"] = answer_row(ans.to_answer_dict(), q["gold_facts"], q["gold_doc_ids"], ctx_docs, q.get("injection_present"))
        row["tokens"] = ans.usage
        row["dropped_claims"] = ans.dropped_claims
        row["unsupported_numbers"] = sum(len(c.unsupported_numbers) for c in ans.claims)
        if a.oracle:
            g = gold_hits(idx, q["gold_doc_ids"])
            oans = generate(qn, g, as_of=q["request"]["as_of"], cfg=cfg, tag="rag_oracle")
            row["oracle"] = answer_row(oans.to_answer_dict(), q["gold_facts"], q["gold_doc_ids"], list(dict.fromkeys(c.split("#")[0] for c in oans.context_chunks)))
        rows.append(row)
        preds.append({"id": q["id"], "response": ans.to_answer_dict()})
        print(f"{q['id']} {q['category'][:14]:14s} ctx_recall={row['answer']['context_recall']} facts={row['answer']['fact_recall']} -> {row['answer']['diagnosis']}"
              + (f" | oracle facts={row['oracle']['fact_recall']}" if a.oracle else ""))
    n = max(1, len(rows))
    mean = lambda f: round(sum(f(r) for r in rows) / n, 3)
    summary = dict(queries=len(rows), mode=a.mode, chunking=idx.strategy,
                   retrieval=dict(hit_in_context=mean(lambda r: r["retrieval"]["hit@6"]), recall_in_context=mean(lambda r: r["retrieval"]["recall@6"]),
                                  quote_coverage=mean(lambda r: r["retrieval"].get("quote@6", 0))),
                   answer=dict(pass_rate=mean(lambda r: r["answer"]["passed"]), fact_recall=mean(lambda r: r["answer"]["fact_recall"]),
                               citation_hit=mean(lambda r: r["answer"]["citation_hit"]), citation_precision=mean(lambda r: r["answer"]["citation_precision"])),
                   diagnosis=dict(Counter(r["answer"]["diagnosis"] for r in rows)))
    if a.oracle:
        summary["oracle_answer"] = dict(pass_rate=mean(lambda r: r["oracle"]["passed"]), fact_recall=mean(lambda r: r["oracle"]["fact_recall"]),
                                        diagnosis=dict(Counter(r["oracle"]["diagnosis"] for r in rows)))
    print(json.dumps(summary, indent=1))
    tag = a.mode.replace("+", "_")
    (out_dir / f"answers_{tag}.jsonl").write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in preds) + "\n", encoding="utf-8")
    (out_dir / f"answer_eval_{tag}.json").write_text(json.dumps(dict(run_at=time.strftime("%Y-%m-%d %H:%M"), summary=summary, rows=rows), indent=1), encoding="utf-8")
    print(f"wrote reports/rag/answers_{tag}.jsonl (gradable with scripts.grade) and answer_eval_{tag}.json")


if __name__ == "__main__":
    main()
