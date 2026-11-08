"""Step 1.8: retrieval baselines, measured separately from answer quality.

    python -m scripts.retrieval_baseline                         # BM25 only (no endpoint needed)
    python -m scripts.retrieval_baseline --retrievers bm25,dense # needs the embeddings endpoint (or EMBED_BACKEND=local)

Corpus v1 is chunked with the naive fixed-512-token strategy. For every eval_v1 query that has gold documents, the
query text is the user's question, and we measure DOCUMENT-level retrieval: a chunk counts as a hit for its document.
  hit@k     any gold document among the documents of the top-k chunks
  recall@k  share of the query's gold documents found in the top-k chunks
  MRR       1 / rank of the first chunk from a gold document (within top 50)
Also runs the ACORD clause-retrieval benchmark (CUAD clauses, expert relevance labels) with BM25 as an outside check.
Writes reports/retrieval_baseline_v1.json and the retrieval section of docs/baselines.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from app.retrieval.chunking import ROOT, chunk_corpus, load_corpus, tokenize
from scripts.grade import load_eval

REPORTS = ROOT / "reports"
KS = (5, 10, 20)



def read_doc(path):
    """Read a docs/*.md file as UTF-8; repair files an older version wrote in the Windows default encoding (cp1252)."""
    if not path.exists():
        return "# Week 1 baselines\n\n"
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")

def evaluate(retriever, queries, k_max=50):
    per_q = []
    for q in queries:
        gold = set(q["gold_doc_ids"])
        t0 = time.time()
        hits = retriever.search(q["request"]["question"], k=k_max)
        ms = (time.time() - t0) * 1000
        docs_in_order = [c.doc_id for c, _ in hits]
        row = dict(id=q["id"], category=q["category"], split=q["split"], n_gold=len(gold), latency_ms=round(ms, 1))
        for k in KS:
            top = set(docs_in_order[:k])
            row[f"hit@{k}"] = int(bool(top & gold))
            row[f"recall@{k}"] = round(len(top & gold) / len(gold), 3)
        rank = next((i + 1 for i, d in enumerate(docs_in_order) if d in gold), None)
        row["mrr"] = round(1 / rank, 3) if rank else 0.0
        row["top3"] = docs_in_order[:3]
        per_q.append(row)
    return per_q


def summarise(rows, by="category"):
    groups = defaultdict(list)
    for r in rows:
        groups["ALL"].append(r)
        groups[r[by]].append(r)
    out = {}
    for g, rs in groups.items():
        out[g] = {"n": len(rs), **{m: round(sum(r[m] for r in rs) / len(rs), 3)
                                    for m in [f"hit@{k}" for k in KS] + [f"recall@{k}" for k in KS] + ["mrr"]},
                  "median_latency_ms": sorted(r["latency_ms"] for r in rs)[len(rs) // 2]}
    return out


# ------------------------------------------------------------------ ACORD (external benchmark)
def acord_bm25(split="test"):
    from rank_bm25 import BM25Okapi
    base = ROOT / "data/raw/procurement_dataset/Contract Analysis Datasets/ACORD/ACORD Dataset & ReadMe/ACORD Dataset & ReadMe (external)"
    if not base.exists():
        return None
    corpus = [json.loads(l) for l in open(base / "corpus.jsonl", encoding="utf-8")]
    queries = {json.loads(l)["_id"]: json.loads(l)["text"] for l in open(base / "queries.jsonl", encoding="utf-8")}
    qrels = defaultdict(dict)
    for r in csv.DictReader(open(base / f"qrels/{split}.tsv", encoding="utf-8"), delimiter="\t"):
        qrels[r["query-id"]][r["corpus-id"]] = int(r["score"])
    ids = [c["_id"] for c in corpus]
    bm = BM25Okapi([tokenize(c["text"]) for c in corpus])

    def ndcg(rels_ranked, ideal, k):
        dcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels_ranked[:k]))
        idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(sorted(ideal, reverse=True)[:k]))
        return dcg / idcg if idcg else 0.0

    res = defaultdict(list)
    for qid, rel in qrels.items():
        if qid not in queries:
            continue
        sc = bm.get_scores(tokenize(queries[qid]))
        order = sorted(range(len(ids)), key=lambda i: -sc[i])[:10]
        ranked = [rel.get(ids[i], 0) for i in order]
        res["ndcg@5"].append(ndcg(ranked, list(rel.values()), 5))
        res["ndcg@10"].append(ndcg(ranked, list(rel.values()), 10))
        pos = {d for d, s in rel.items() if s >= 2}   # qrels use 0-4 (= stars - 1); 3+ stars (relevant) = label >= 2
        if pos:
            res["recall@10(3+ stars)"].append(len({ids[i] for i in order} & pos) / len(pos))
    return {"split": split, "queries": len(res["ndcg@5"]), **{k: round(sum(v) / len(v), 3) for k, v in res.items()}}


# ------------------------------------------------------------------ report
def write_markdown(report):
    lines = ["## Step 1.8: Retrieval baselines", "",
             f"Run {report['run_at']} on corpus v1 ({report['documents']} documents → {report['chunks']} fixed 512-token chunks, 64-token overlap). "
             "Document-level metrics on eval_v1 queries that have gold documents; the query is the user's raw question (no rewriting).", ""]
    for name, res in report["retrievers"].items():
        if "error" in res:
            lines += [f"### {name}", "", f"Not run: {res['error']}", ""]
            continue
        for split, summ in res["summary"].items():
            lines += [f"### {name}: {split} split", "", "| Category | n | hit@5 | hit@10 | recall@5 | recall@10 | recall@20 | MRR |", "|---|---|---|---|---|---|---|---|"]
            for cat, m in sorted(summ.items(), key=lambda x: (x[0] != "ALL", x[0])):
                lines.append(f"| {'**ALL**' if cat == 'ALL' else cat} | {m['n']} | {m['hit@5']} | {m['hit@10']} | {m['recall@5']} | {m['recall@10']} | {m['recall@20']} | {m['mrr']} |")
            lines.append("")
    if report.get("acord"):
        a = report["acord"]
        lines += ["### External check: ACORD clause retrieval (BM25)", "",
                  f"{a['queries']} {a['split']}-split attorney queries over 3,931 CUAD clauses with expert 1–5 star labels (qrels 0–4): "
                  f"NDCG@5 **{a['ndcg@5']}**, NDCG@10 **{a['ndcg@10']}**, recall@10 of 3+ star clauses **{a['recall@10(3+ stars)']}**. "
                  "ACORD queries are short legal phrases (e.g. 'Audit Rights') with ~10 relevant clauses each among thousands of near-misses from the same category; "
                  "lexical overlap alone ranks those near-misses as high as the relevant clauses. This is the case for dense retrieval plus a reranker.", ""]
    lines += ["### Reading these numbers", "",
              "- Full reviews have about 10 gold documents each, so recall@k is low by construction; hit@k is the fairer view for them. A single question cannot retrieve a whole review package, which is why the Week 3 agent retrieves per checklist item.",
              "- Low recall on vendor questions usually means the right vendor's documents are outranked by look-alike documents from other vendors (all synthetic vendors share templates). Metadata filtering by `vendor_id` (Week 2) is the expected fix.",
              "- The worst queries for each retriever are listed under `worst_queries` in `reports/retrieval_baseline_v1.json`.", ""]
    path = ROOT / "docs" / "baselines.md"
    existing = read_doc(path)
    start = existing.find("## Step 1.8")
    if start >= 0:
        end = existing.find("\n## ", start + 5)
        existing = existing[:start] + existing[end + 1:] if end >= 0 else existing[:start]
    path.write_text(existing.rstrip() + "\n\n" + "\n".join(lines), encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrievers", default="bm25")
    ap.add_argument("--splits", default="dev,test")
    a = ap.parse_args()
    docs = load_corpus()
    chunks = chunk_corpus(docs, "fixed512")
    queries = [q for q in load_eval() if q["gold_doc_ids"]]
    report = dict(run_at=time.strftime("%Y-%m-%d %H:%M"), documents=len(docs), chunks=len(chunks), chunking="fixed512 (overlap 64)",
                  queries_with_gold_docs=len(queries), retrievers={})
    for name in a.retrievers.split(","):
        try:
            if name == "bm25":
                from app.retrieval.retrievers import BM25Retriever
                r = BM25Retriever(chunks)
            elif name == "dense":
                from app.retrieval.retrievers import DenseRetriever
                r = DenseRetriever(chunks)
            else:
                raise ValueError(name)
        except Exception as e:  # endpoint not configured / model unavailable
            msg = ("embeddings endpoint not configured: set EMBED_BASE_URL / EMBED_MODEL in .env, or run on a laptop with "
                   "EMBED_BACKEND=local (downloads BAAI/bge-small-en-v1.5)") if isinstance(e, KeyError) else f"{type(e).__name__}: {e}"[:300]
            report["retrievers"][name] = {"error": msg}
            print(name, "SKIPPED:", report["retrievers"][name]["error"])
            continue
        rows = evaluate(r, queries)
        report["retrievers"][name] = {
            "summary": {s: summarise([x for x in rows if x["split"] == s]) for s in a.splits.split(",")},
            "per_query": rows,
            "worst_queries": sorted([x for x in rows if x["category"] != "full_review"], key=lambda x: (x["mrr"], x["recall@10"]))[:10]}
        for s in a.splits.split(","):
            m = report["retrievers"][name]["summary"][s]["ALL"]
            print(f"{name:6s} {s:4s} n={m['n']:3d} hit@5={m['hit@5']} hit@10={m['hit@10']} recall@10={m['recall@10']} mrr={m['mrr']}")
    report["acord"] = acord_bm25("test")
    if report["acord"]:
        print("ACORD BM25:", report["acord"])
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "retrieval_baseline_v1.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    write_markdown(report)


if __name__ == "__main__":
    main()
