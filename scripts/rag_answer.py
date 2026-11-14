"""Ask one question and see retrieved passages plus the cited answer.

    python -m scripts.rag_answer "What is Kestrion's auto-renewal notice period?" --vendor V009
    python -m scripts.rag_answer "Who must approve a 3 crore renewal?" --chunking heading --mode hybrid+rerank
"""
import argparse
import json

from app.rag.config import settings
from app.rag.index import HybridIndex
from app.rag.pipeline import RagPipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--vendor", action="append", help="vendor id(s); default: detected from the question")
    ap.add_argument("--chunking", default=None)
    ap.add_argument("--mode", default="hybrid+rerank")
    ap.add_argument("--as-of", default="2026-11-01")
    ap.add_argument("--retrieve-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = settings()
    pipe = RagPipeline(HybridIndex.load(a.chunking or cfg.chunking, cfg=cfg), cfg)
    if a.retrieve_only:
        r = pipe.retrieve(a.question, vendor_ids=a.vendor, mode=a.mode)
        ans = None
    else:
        r, ans = pipe.answer(a.question, vendor_ids=a.vendor, as_of=a.as_of, mode=a.mode)
    print(f"vendors={r.vendor_ids or 'none detected'} mode={r.mode} retrieval={r.ms}ms {r.note}")
    for i, h in enumerate(r.final, 1):
        print(f"  S{i} {h.chunk.doc_id:28s} score={h.score:.3f} {h.chunk.section[:50]}")
    if ans:
        print("\nANSWER:", ans.answer)
        if ans.dropped_claims:
            print(f"(dropped {ans.dropped_claims} uncited claims)")
        for c in ans.claims:
            if c.unsupported_numbers:
                print(f"  warning: numbers not found in cited text: {c.unsupported_numbers}")
        if a.json:
            print(json.dumps(ans.to_answer_dict(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
