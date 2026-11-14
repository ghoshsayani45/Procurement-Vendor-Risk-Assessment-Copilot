"""Run the Week 3 copilot on eval_v1 and grade it with scripts.grade (same grader as the Week 1 baselines).

    python -m scripts.run_copilot                       # dev split, no LLM calls (structured answers + extractive fallback)
    python -m scripts.run_copilot --llm endpoint        # dev split, course model for open questions
    python -m scripts.run_copilot --one EVAL-006        # one query, full response and trace
    python -m scripts.run_copilot --split test --allow-test   # ONLY at the Week 3 / Week 4 gates (decision D12)

Writes reports/copilot/predictions_<split>_<llm>.jsonl, traces_<split>_<llm>.jsonl and copilot_<split>_<llm>.json.
"""
import argparse
import json
import os
import time
from pathlib import Path

from app.agents.copilot import run
from scripts.grade import grade

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "evaluation" / "eval_v1.jsonl"
OUT = ROOT / "reports" / "copilot"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--llm", default="none", choices=["none", "mock", "endpoint"])
    ap.add_argument("--llm-summary", action="store_true")
    ap.add_argument("--one")
    a = ap.parse_args()
    if a.split != "dev" and not a.allow_test:
        raise SystemExit("Refusing to run on the test split (decision D12). Use --allow-test only at an official gate.")
    os.environ.setdefault("AUDIT_LOG_PATH", str(ROOT / "observability" / "audit_events.jsonl"))
    qs = [json.loads(l) for l in open(EVAL, encoding="utf-8") if l.strip()]
    qs = [q for q in qs if (a.split == "all" or q["split"] == a.split) and (not a.one or q["id"] == a.one)]
    preds, traces = {}, []
    t0 = time.time()
    for q in qs:
        out = run(q["request"], llm=a.llm, llm_summary=a.llm_summary)
        preds[q["id"]] = out["response"]
        traces.append(dict(id=q["id"], category=q["category"], **out["trace"]))
        if a.one:
            print(json.dumps(out, indent=1))
    summary, results = grade(preds, a.split)
    summary["tool_calls_per_query"] = round(sum(t["tool_calls"] for t in traces) / max(1, len(traces)), 2)
    summary["median_latency_ms"] = sorted(t["latency_ms"] for t in traces)[len(traces) // 2] if traces else 0
    summary["llm"] = a.llm
    summary["run_at"] = time.strftime("%Y-%m-%d %H:%M")
    if a.one:
        print(json.dumps([r for r in results if r["id"] == a.one][0], indent=1))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"{a.split}_{a.llm}"
    (OUT / f"predictions_{tag}.jsonl").write_text("".join(json.dumps(dict(id=k, response=v), ensure_ascii=False) + "\n" for k, v in preds.items()), encoding="utf-8")
    (OUT / f"traces_{tag}.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces), encoding="utf-8")
    (OUT / f"copilot_{tag}.json").write_text(json.dumps(dict(summary=summary, results=results), indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print("failed:", [r["id"] + " " + r["category"] + " " + json.dumps({k: v for k, v in r["checks"].items() if v in (False, 0) or (isinstance(v, float) and v < 1)})
                      for r in results if not r["passed"]])
    print(f"{len(qs)} queries in {time.time() - t0:.1f}s -> reports/copilot/copilot_{tag}.json")


if __name__ == "__main__":
    main()
