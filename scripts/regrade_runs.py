"""Re-grade saved prompt-baseline runs WITHOUT calling the model again.

    python -m scripts.regrade_runs              # latest complete dev run of each strategy -> reports/ + docs/
    python -m scripts.regrade_runs --split test

Use it after fixing the grader (scripts/grade.py) or the failure classifier (app/failure_analysis.py): it re-reads the
raw responses saved in runs/prompt_baseline/, recomputes grades and failure labels, and rewrites
reports/prompt_baseline_v1.json, the Step 1.6 table in docs/baselines.md, and docs/failure_log.md.
Only runs that covered the whole split are used (smoke runs with --limit are skipped).
"""
from __future__ import annotations

import argparse
import json
import os
import time

from app.failure_analysis import classify, summarise
from collections import Counter

from app import prompting as P
from app.prompting import STRATEGIES
from scripts.grade import grade_one, load_eval
from scripts.prompt_baseline import ROOT, metrics, serialise_examples, write_docs


def revalidate(q, raws, strategy):
    """Re-check saved raw replies with the current validation (e.g. new label normalisation). No API calls."""
    P.CURRENT_REQUEST.clear()
    P.CURRENT_REQUEST.update(q["request"])
    valid = []
    for raw in raws:
        obj, _ = P.parse_json(raw or "")
        if obj is not None and "sub_questions" not in obj:
            resp, _ = P.validate(obj, q["request"]["request_kind"])
            if resp is not None:
                valid.append(resp)
    if not valid:
        return None
    if strategy == "cot_sc":                       # same majority vote as the live run
        top, _ = Counter(P._vote_key(v) for v in valid).most_common(1)[0]
        group = [v for v in valid if P._vote_key(v) == top]
        return P._medoid(group) if top == ("ANSWER",) else group[0]
    return valid[-1]                               # the final (retry) reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    a = ap.parse_args()
    qs = {q["id"]: q for q in load_eval() if a.split == "all" or q["split"] == a.split}
    base = ROOT / "runs" / "prompt_baseline"
    report = dict(model=os.environ.get("LLM_MODEL", "?"), backend="endpoint", split=a.split, strategies={}, regraded_at=time.strftime("%Y-%m-%d %H:%M"))
    labelled = {}
    for s in STRATEGIES:
        files = [f for f in base.glob(f"*/{s}.jsonl") if not f.parent.name.startswith("mock_")]
        complete = []
        for f in files:
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            if {r["id"] for r in rows} == set(qs):
                complete.append((f.stat().st_mtime, f, rows))
        if not complete:
            print(f"{s}: no complete {a.split} run found, skipped")
            continue
        _, f, rows = max(complete, key=lambda x: x[0])
        trip, lab = [], []
        revalidated = 0
        for r in rows:
            q = qs[r["id"]]
            if r.get("response") is None and r.get("raw") and not r.get("call_error"):
                r["response"] = revalidate(q, r["raw"], s)
                revalidated += r["response"] is not None
            g = grade_one(q, r.get("response"))
            labels = classify(q, r, g)
            trip.append((q, r, g)); lab.append((q, r, g, labels))
        labelled[s] = lab
        res = metrics(trip)
        print(f"{s}: {f.parent.name}  accuracy={res['accuracy']}  ({len(rows)} queries; {revalidated} rejected replies now parse)")
        report["strategies"][s] = dict(run_at=time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)), results=res,
                                       raw_dir=str(f.parent.relative_to(ROOT)))
    counts, traps, examples = summarise(labelled)
    for s in report["strategies"]:
        report["strategies"][s].update(failure_counts=dict(counts.get(s, {})), trap_failures=dict(traps.get(s, {})),
                                       examples=serialise_examples(examples, s))
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "prompt_baseline_v1.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_docs(report, ROOT / "docs")
    print("Rewrote reports/prompt_baseline_v1.json, docs/baselines.md (Step 1.6) and docs/failure_log.md")


if __name__ == "__main__":
    main()
