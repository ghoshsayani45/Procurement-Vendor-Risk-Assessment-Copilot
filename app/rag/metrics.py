"""Retrieval metrics and answer metrics, computed separately.

Retrieval (needs no LLM):  hit@k, recall@k and MRR over gold DOCUMENTS; nDCG@k; and quote_coverage@k = the share of gold QUOTES that
appear verbatim inside the top-k chunks (stricter, because it checks that the chunking kept the evidence sentence intact).
Answer (needs the LLM):    fact recall, citation hit/precision, injection flag, plus a diagnosis that says WHY a query failed.

Diagnosis labels (the key diagnostic for a weak generator):
  ok                     facts present and a gold document cited
  retrieval_miss         no gold document in the context the model saw -> fix retrieval
  retrieval_partial      some gold documents missing from the context
  generator_miss         every gold document was in the context but the facts are wrong or missing -> fix prompting/model
  citation_error         facts right but no gold document cited
"""
from __future__ import annotations

import math
import re

KS = (1, 3, 5, 6, 10, 20)


def norm(text: str) -> str:
    return re.sub(r"[\s*_`|>#\\-]+", " ", text).strip().lower()


def unique_docs(hits) -> list[str]:
    seen, out = set(), []
    for h in hits:
        d = h.chunk.doc_id if hasattr(h, "chunk") else h
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def retrieval_row(hits, gold_docs: list[str], gold_quotes: list[dict] | None = None, ks=KS) -> dict:
    gold = set(gold_docs)
    docs = unique_docs(hits)
    row: dict = {"n_gold": len(gold)}
    for k in ks:
        top = set(docs[:k])
        row[f"hit@{k}"] = int(bool(top & gold))
        row[f"recall@{k}"] = round(len(top & gold) / len(gold), 3) if gold else 0.0
        dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(docs[:k]) if d in gold)
        idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
        row[f"ndcg@{k}"] = round(dcg / idcg, 3) if idcg else 0.0
    rank = next((i + 1 for i, d in enumerate(docs) if d in gold), None)
    row["mrr"] = round(1 / rank, 3) if rank else 0.0
    if gold_quotes:
        for k in ks:
            texts = norm(" ".join((h.chunk.text + " " + (h.chunk.parent_text or "")) for h in hits[:k]))
            found = sum(1 for q in gold_quotes if norm(q["quote"]) in texts)
            row[f"quote@{k}"] = round(found / len(gold_quotes), 3)
    return row


def summarise(rows: list[dict], group_key: str = "category") -> dict:
    out: dict = {}
    groups: dict[str, list[dict]] = {"ALL": rows}
    for r in rows:
        groups.setdefault(r[group_key], []).append(r)
    metric_keys = sorted({k for r in rows for k in r if k.startswith(("hit@", "recall@", "ndcg@", "quote@")) or k == "mrr"},
                         key=lambda s: (s.split("@")[0], int(s.split("@")[1]) if "@" in s else 0))
    for g, rs in groups.items():
        out[g] = {"n": len(rs)}
        for m in metric_keys:
            vals = [r[m] for r in rs if m in r]
            if vals:
                out[g][m] = round(sum(vals) / len(vals), 3)
        lat = sorted(r.get("latency_ms", 0) for r in rs)
        out[g]["median_latency_ms"] = lat[len(lat) // 2] if lat else 0
    return out


# ------------------------------------------------------------------ answer metrics + diagnosis
def _has_fact(text: str, fact: str) -> bool:
    try:
        from scripts.grade import has_fact
        return has_fact(text, fact)
    except Exception:
        return any(a.strip().lower() in text.lower() for a in fact.split("|"))


def answer_row(answer_dict: dict, gold_facts: list[str], gold_docs: list[str], context_docs: list[str], injection_present=None) -> dict:
    text = answer_dict.get("answer", "")
    cited = {c.get("doc_id") for c in answer_dict.get("citations", []) if c.get("doc_id")}
    gold, ctx = set(gold_docs), set(context_docs)
    fact_recall = (sum(_has_fact(text, f) for f in gold_facts) / len(gold_facts)) if gold_facts else 1.0
    cite_hit = bool(cited & gold) if gold else True
    cite_prec = round(len(cited & gold) / len(cited), 3) if cited else 0.0
    ctx_recall = len(ctx & gold) / len(gold) if gold else 1.0
    if fact_recall == 1.0 and cite_hit:
        diag = "ok"
    elif gold and not (ctx & gold):
        diag = "retrieval_miss"
    elif fact_recall < 1.0 and ctx_recall < 1.0:
        diag = "retrieval_partial"
    elif fact_recall < 1.0:
        diag = "generator_miss"
    else:
        diag = "citation_error"
    row = dict(fact_recall=round(fact_recall, 3), citation_hit=int(cite_hit), citation_precision=cite_prec, context_recall=round(ctx_recall, 3),
               passed=int(fact_recall == 1.0 and cite_hit), diagnosis=diag)
    if injection_present is not None:
        row["injection_flagged"] = int(bool(answer_dict.get("injection_detected")) == bool(injection_present))
    return row
