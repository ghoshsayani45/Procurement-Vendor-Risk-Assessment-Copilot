"""Step 1.4 exit check: can plain BM25 find the right document for obvious queries?

    python -m scripts.retrieval_smoke_test

Document-level BM25 (no chunking, no embeddings) - a sanity check that ingestion kept the text searchable,
not the Week 1 baseline (that is step 1.8, on chunks, measured on eval_v1).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOK = re.compile(r"[a-z0-9]+")
STOP = set("the a an of to in and or for on by with is are be as at this that from any all its it shall may".split())

QUERIES = [
    ("Kestrion Customer Cloud renewal notice period automatic renewal", "DOC-V009-CONTRACT-1"),
    ("Payvanta Workforce ISO 27001 certificate expiry date", "DOC-V003-ISO27001-1"),
    ("Data Fiduciary intimation of personal data breach to the Board within seventy-two hours", "POL-006-"),
    ("internal debarment list Opticrest Surveillance", "POLICY-DEBARMENT-LIST"),
    ("delegation of authority approval limits Head of Procurement Finance Controller", "POLICY-DOA-002"),
    ("Wardlock penetration test open critical findings", "DOC-V007-PENTEST-1"),
    ("cybersecurity supply chain risk management practices C-SCRM", "GUI-001-"),
    ("Coinharbor Payments summary financial statements current ratio", "DOC-V024-FIN-"),
    ("conflict of interest register Bytemarsh undeclared", "COI-REGISTER"),
    ("supply chain management transparency accountability STA controls", "GUI-002-"),
]


def toks(t):
    return [w for w in TOK.findall(t.lower()) if w not in STOP]


def main(k=5):
    docs = [json.loads(l) for l in open(ROOT / "data/processed/corpus_v1.jsonl")]
    tf = [Counter(toks(d["title"] + " " + d["text"])) for d in docs]
    lens = [sum(c.values()) for c in tf]
    avg = sum(lens) / len(lens)
    df = Counter(w for c in tf for w in c)
    N = len(docs)

    def score(q, i, k1=1.2, b=0.75):
        s = 0.0
        for w in q:
            if w in tf[i]:
                idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
                f = tf[i][w]
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * lens[i] / avg))
        return s

    hits = 0
    for q, expect in QUERIES:
        qt = toks(q)
        top = sorted(range(N), key=lambda i: -score(qt, i))[:k]
        ids = [docs[i]["doc_id"] for i in top]
        ok = any(x.startswith(expect) for x in ids)
        hits += ok
        print(("PASS" if ok else "MISS"), f"{q[:60]:60s} -> {ids[0]}")
    print(f"\nhit@{k}: {hits}/{len(QUERIES)}")
    return hits, len(QUERIES)


if __name__ == "__main__":
    h, n = main()
    if h < n - 1:
        raise SystemExit("smoke test failed: check extraction")
