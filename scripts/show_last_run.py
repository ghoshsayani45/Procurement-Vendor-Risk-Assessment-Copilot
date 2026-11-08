"""Show what the model actually returned in the latest prompt-baseline run.

    python -m scripts.show_last_run                 # every query of every strategy in the latest run
    python -m scripts.show_last_run EVAL-005        # one query
    python -m scripts.show_last_run --chars 4000    # show more of each raw reply
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query_id", nargs="?")
    ap.add_argument("--chars", type=int, default=1500)
    a = ap.parse_args()
    runs = sorted((ROOT / "runs" / "prompt_baseline").glob("*/"), key=lambda p: p.stat().st_mtime)
    runs = [r for r in runs if not r.name.startswith("mock_")]
    if not runs:
        print("No real runs found under runs/prompt_baseline/.")
        return
    run = runs[-1]
    print(f"Run folder: {run}\n")
    for f in sorted(run.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if a.query_id and r["id"] != a.query_id:
                continue
            print("=" * 100)
            print(f"{f.stem} | {r['id']} | labels: {', '.join(r.get('labels', []))}")
            print(f"calls={r.get('calls')} tokens={r.get('tokens')} prompt_tokens={r.get('prompt_tokens')} "
                  f"finish_reasons={r.get('finish_reasons')}  context_words={r.get('context_words')}")
            if r.get("truncated"):
                print("!! TRUNCATED: the reply hit max_tokens (finish_reason=length). Raise PROMPT_MAX_TOKENS or lower PROMPT_CONTEXT_WORDS.")
            print(f"first-attempt error: {r.get('first_error')}")
            print(f"final error: {r.get('error')}")
            for i, raw in enumerate(r.get("raw") or []):
                raw = raw or ""
                print(f"--- raw reply {i + 1} ({len(raw)} chars){' [last ' + str(a.chars) + ' shown below too]' if len(raw) > a.chars else ''}")
                print(raw[: a.chars])
                if len(raw) > a.chars:
                    print("   ...")
                    print(raw[-300:])
            print()


if __name__ == "__main__":
    main()
