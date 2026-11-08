"""Steps 1.6 + 1.7: run the three prompting strategies on eval_v1 (dev split by default), grade them, classify failures.

    python -m scripts.prompt_baseline                                  # all 3 strategies, dev split, course endpoint
    python -m scripts.prompt_baseline --strategies structured_fewshot --limit 5   # quick smoke run
    LLM_BACKEND=mock python -m scripts.prompt_baseline                 # offline pipeline test (numbers meaningless)

Outputs (real endpoint):  runs/prompt_baseline/<timestamp>/<strategy>.jsonl  (raw outputs; not in Git)
                          reports/prompt_baseline_v1.json                     (metrics; committed)
                          docs/baselines.md  section "Step 1.6"                (comparison table)
                          docs/failure_log.md                                 (step 1.7, generated; team notes go in docs/failure_notes.md)
Runs of different strategies are MERGED: run them one at a time and the docs show all of them side by side.
--limit runs are smoke tests: they write to reports/smoke/ and never touch docs/.
Mock runs write only under reports/mock/ and never touch docs/.
Token budget: dev split = 30 queries; fewshot 1-2 calls, cot_sc 3-6, decomposition 2-3 per query.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from app import llm_client
from app.failure_analysis import classify, summarise
from app.prompting import STRATEGIES, run_query
from scripts.grade import grade_one, load_eval

ROOT = Path(__file__).resolve().parents[1]



def read_doc(path):
    """Read a docs/*.md file as UTF-8; repair files an older version wrote in the Windows default encoding (cp1252)."""
    if not path.exists():
        return "# Week 1 baselines\n\n"
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")

def run(strategies, split, limit, out_dir):
    qs = [q for q in load_eval() if split == "all" or q["split"] == split][: limit or None]
    results, labelled = {}, {}
    for s in strategies:
        rows, lab, call_errors = [], [], 0
        with open(out_dir / f"{s}.jsonl", "w", encoding="utf-8") as fh:
            for i, q in enumerate(qs, 1):
                try:
                    r = run_query(q, s)
                except llm_client.QuotaExceeded as e:
                    print("STOP:", e); break
                except Exception as e:  # network / provider / code error: record, show, continue
                    import traceback
                    r = dict(id=q["id"], strategy=s, response=None, raw=[], error=f"{type(e).__name__}: {e}"[:500],
                             valid_first_try=False, calls=0, tokens=0, latency_ms=0, context_docs=[], call_error=True)
                    print(f"  ERROR on {q['id']}: {r['error']}")
                    if call_errors == 0:
                        traceback.print_exc()
                    call_errors += 1
                    if call_errors >= 3 and not rows_ok(rows):
                        print(f"\nSTOP: 3 errors and no successful call with '{s}'. Fix the error above "
                              "(run `python -m scripts.check_endpoint`) before spending more time or tokens.")
                        raise SystemExit(1)
                g = grade_one(q, r["response"])
                labels = classify(q, r, g)
                rows.append((q, r, g)); lab.append((q, r, g, labels))
                fh.write(json.dumps({**{k: v for k, v in r.items() if k != "parsed"}, "grade": g, "labels": labels}, ensure_ascii=False, default=str) + "\n")
                print(f"[{s}] {i}/{len(qs)} {q['id']} {q['category']:30s} {'PASS' if g['passed'] else 'fail'} {','.join(labels)[:80]}")
        results[s] = metrics(rows)
        labelled[s] = lab
    return qs, results, labelled


def rows_ok(rows):
    return any(r.get("calls", 0) > 0 for _, r, _ in rows)


def metrics(rows):
    n = len(rows)
    if not n:
        return {}
    g = [x[2] for x in rows]
    r = [x[1] for x in rows]

    def m(key):
        v = [x["checks"][key] for x in g if key in x["checks"]]
        return round(sum(v) / len(v), 3) if v else None
    by_cat = {}
    for q, _, gg in rows:
        by_cat.setdefault(q["category"], []).append(gg["passed"])
    return dict(
        queries=n, accuracy=round(sum(x["passed"] for x in g) / n, 3),
        by_category={k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_cat.items())},
        json_valid_first_try=round(sum(bool(x.get("valid_first_try")) for x in r) / n, 3),
        json_valid_final=round(sum(x.get("response") is not None for x in r) / n, 3),
        band_accuracy=m("band_ok"), recommendation_accuracy=m("recommendation_ok"), checklist_accuracy=m("checklist_accuracy"),
        finding_recall=m("finding_recall"), fact_recall=m("fact_recall"), citation_hit_rate=m("citation_hit"),
        refusal_accuracy=m("category_ok"), injection_resistance=m("injection_flagged"), pii_leak_free=m("must_not_ok"),
        calls_per_query=round(sum(x.get("calls", 0) for x in r) / n, 2),
        tokens_per_query=int(sum(x.get("tokens", 0) for x in r) / n),
        median_latency_ms=int(statistics.median([x.get("latency_ms", 0) for x in r])))


METRIC_ROWS = ["accuracy", "json_valid_first_try", "json_valid_final", "band_accuracy", "recommendation_accuracy", "checklist_accuracy",
               "finding_recall", "fact_recall", "citation_hit_rate", "refusal_accuracy", "injection_resistance", "pii_leak_free",
               "calls_per_query", "tokens_per_query", "median_latency_ms"]


def serialise_examples(examples, strategy):
    """examples[label] = [(strategy, q, run)] -> JSON-safe dicts for this strategy (max 2 per label)."""
    out = {}
    for label, items in examples.items():
        for s, q, r in items:
            if s != strategy:
                continue
            got = json.dumps(r.get("response"), ensure_ascii=False)[:500] if r.get("response") else ((r.get("raw") or [""])[-1] or "")[:500]
            out.setdefault(label, []).append(dict(id=q["id"], category=q["category"], question=q["request"]["question"],
                                                  expected=q["gold_answer"][:300], got=got, error=r.get("error"),
                                                  first_error=r.get("first_error")))
    return out


def write_docs(report, target_dir):
    """Render docs from the MERGED report, so strategies run separately all appear side by side."""
    S = report["strategies"]
    names = [s for s in STRATEGIES if s in S] + [s for s in S if s not in STRATEGIES]
    model, split = report["model"], report["split"]
    runs_line = "; ".join(f"`{s}` {S[s]['run_at']} ({S[s]['results'].get('queries')} queries)" for s in names)
    t = ["## Step 1.6: Prompting baseline (single agent, single prompt, gold passages pasted in)", "",
         f"Model `{model}` · eval_v1 **{split}** split · context = gold documents (retrieval not tested here).",
         f"Runs: {runs_line}.", "",
         "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in METRIC_ROWS:
        t.append(f"| {k} | " + " | ".join(str(S[s]["results"].get(k)) for s in names) + " |")
    t += ["", "| Category | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    cats = sorted({c for s in names for c in S[s]["results"].get("by_category", {})})
    for c in cats:
        t.append(f"| {c} | " + " | ".join(S[s]["results"].get("by_category", {}).get(c, "-") for s in names) + " |")
    t += ["", "Strategy definitions are in `app/prompting.py`; raw outputs in `runs/prompt_baseline/`. "
              "Failure analysis: `docs/failure_log.md` (generated) and `docs/failure_notes.md` (team notes).", ""]
    path = target_dir / "baselines.md"
    existing = read_doc(path)
    start = existing.find("## Step 1.6")
    if start >= 0:
        end = existing.find("\n## ", start + 5)
        existing = existing[:start] + (existing[end + 1:] if end >= 0 else "")
    head, sep, rest = existing.partition("\n## ")
    path.write_text(head.rstrip() + "\n\n" + "\n".join(t) + ("\n## " + rest if sep else "\n"), encoding="utf-8", newline="\n")

    counts = {s: S[s]["failure_counts"] for s in names}
    traps = {s: S[s]["trap_failures"] for s in names}
    all_labels = sorted({l for c in counts.values() for l in c}, key=lambda l: -sum(c.get(l, 0) for c in counts.values()))
    f = ["# Step 1.7: How the small model breaks (failure log)", "",
         "> **Generated file: do not edit.** It is rewritten after every full run of `scripts/prompt_baseline.py`.",
         "> Write team observations in `docs/failure_notes.md`, which the script never touches.", "",
         f"Model `{model}` · eval_v1 {split} split · runs: {runs_line} · labels from `app/failure_analysis.py`.", "",
         "## Failure counts (queries affected)", "", "| Failure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for l in all_labels:
        f.append(f"| {l} | " + " | ".join(str(counts[s].get(l, 0)) for s in names) + " |")
    trap_labels = sorted({l for c in traps.values() for l in c})
    if trap_labels:
        f += ["", "## Traps that caught the model", "", "| Trap | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for l in trap_labels:
            f.append(f"| {l[5:]} | " + " | ".join(str(traps[s].get(l, 0)) for s in names) + " |")
    f += ["", "## Examples (up to 2 per failure and strategy)", ""]
    for l in all_labels:
        for s in names:
            for ex in S[s].get("examples", {}).get(l, [])[:2]:
                f += [f"### {l} · {s} · {ex['id']} ({ex['category']})", "", f"- **Question:** {ex['question']}",
                      f"- **Expected:** {ex['expected']}", f"- **Got:** `{ex['got']}`",
                      f"- **First-attempt error:** {ex.get('first_error') or '-'}", f"- **Final error:** {ex.get('error') or '-'}", ""]
    (target_dir / "failure_log.md").write_text("\n".join(f) + "\n", encoding="utf-8", newline="\n")


NOTES_TEMPLATE = """# Step 1.7: Team notes on model failures

Hand-written; `scripts/prompt_baseline.py` never overwrites this file. The generated counts and examples are in `docs/failure_log.md`.

## Observations
| Failure | What we saw (query ids) | Why we think it happens | Owner |
|---|---|---|---|
| | | | |

## Mitigations to try in Weeks 2-3 (fill in before/after numbers)
| Failure | Mitigation | Before | After |
|---|---|---|---|
| JSON_INVALID / JSON_NEEDED_RETRY | Smaller per-call schemas; constrained decoding if the endpoint supports it; repair retry | | |
| SCORE_ARITHMETIC / WRONG_BAND | Scores computed by the deterministic engine tool, never by the LLM | | |
| MISSING_AS_COMPLIANT / EXPIRED_AS_VALID | compliance_checker tool computes statuses from dates; LLM only explains | | |
| INJECTION_* | Delimit retrieved text as data; strip instruction-like lines; critic checks verdict against tool output | | |
| INVENTED_CITATION / INVENTED_FINDING_CODE | Critic verifies cited ids and codes against the retrieved set and the rubric | | |
| MISSED_REFUSAL / OVER_REFUSAL | Rule-based pre-classifier for approval/sign/PII/secrets before the LLM | | |
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--limit", type=int, default=0, help="smoke test: results go to reports/smoke/, docs/ untouched")
    a = ap.parse_args()
    mock = llm_client.backend() == "mock"
    import os
    model = "mock" if mock else os.environ.get("LLM_MODEL", "?")
    out_dir = ROOT / "runs" / "prompt_baseline" / (("mock_" if mock else "") + time.strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    strategies = a.strategies.split(",")
    qs, results, labelled = run(strategies, a.split, a.limit, out_dir)
    counts, traps, examples = summarise(labelled)

    # where results go: mock -> reports/mock ; --limit -> reports/smoke ; full run -> reports/ + docs/
    if mock:
        rep_dir = doc_dir = ROOT / "reports" / "mock"
    elif a.limit:
        rep_dir = doc_dir = ROOT / "reports" / "smoke"
    else:
        rep_dir, doc_dir = ROOT / "reports", ROOT / "docs"
    rep_dir.mkdir(parents=True, exist_ok=True)
    rep_path = rep_dir / "prompt_baseline_v1.json"

    # merge with earlier runs of OTHER strategies (same model and split); this run's strategies replace their old entries
    report = None
    if rep_path.exists():
        try:
            old = json.loads(rep_path.read_text(encoding="utf-8"))
            if "strategies" in old and old.get("model") == model and old.get("split") == a.split:
                report = old
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    report = report or dict(model=model, backend=llm_client.backend(), split=a.split, strategies={})
    stamp = time.strftime("%Y-%m-%d %H:%M")
    for s in strategies:
        if s not in results:
            continue
        report["strategies"][s] = dict(run_at=stamp, results=results[s], failure_counts=dict(counts.get(s, {})),
                                       trap_failures=dict(traps.get(s, {})), examples=serialise_examples(examples, s),
                                       raw_dir=str(out_dir.relative_to(ROOT)))
    rep_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_docs(report, doc_dir)
    notes = ROOT / "docs" / "failure_notes.md"
    if not notes.exists():
        notes.write_text(NOTES_TEMPLATE, encoding="utf-8", newline="\n")

    print(json.dumps({s: {k: v for k, v in r.items() if k != "by_category"} for s, r in results.items()}, indent=1))
    where = {ROOT / "docs": "docs/baselines.md and docs/failure_log.md (merged with earlier strategy runs)"}.get(doc_dir, str(doc_dir.relative_to(ROOT)) + "/ (docs/ untouched)")
    print(f"\nWritten to: {where}")
    if mock:
        print("MOCK RUN: numbers are meaningless.")


if __name__ == "__main__":
    main()
