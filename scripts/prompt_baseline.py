"""Steps 1.6 + 1.7: run the three prompting strategies on eval_v1 (dev split by default), grade them, classify failures.

    python -m scripts.prompt_baseline                                  # all 3 strategies, dev split, course endpoint
    python -m scripts.prompt_baseline --strategies structured_fewshot --limit 5   # quick smoke run
    LLM_BACKEND=mock python -m scripts.prompt_baseline                 # offline pipeline test (numbers meaningless)

Outputs (real endpoint):  runs/prompt_baseline/<timestamp>/<strategy>.jsonl  (raw outputs; not in Git)
                          reports/prompt_baseline_v1.json                     (metrics; committed)
                          docs/baselines.md  section "Step 1.6"                (comparison table)
                          docs/failure_log.md                                 (step 1.7, with examples to annotate)
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


def run(strategies, split, limit, out_dir):
    qs = [q for q in load_eval() if split == "all" or q["split"] == split][: limit or None]
    results, labelled = {}, {}
    for s in strategies:
        rows, lab = [], []
        with open(out_dir / f"{s}.jsonl", "w") as fh:
            for i, q in enumerate(qs, 1):
                try:
                    r = run_query(q, s)
                except llm_client.QuotaExceeded as e:
                    print("STOP:", e); break
                except Exception as e:  # network / provider error: record and continue
                    r = dict(id=q["id"], strategy=s, response=None, raw=[], error=f"{type(e).__name__}: {e}"[:300],
                             valid_first_try=False, calls=0, tokens=0, latency_ms=0, context_docs=[])
                g = grade_one(q, r["response"])
                labels = classify(q, r, g)
                rows.append((q, r, g)); lab.append((q, r, g, labels))
                fh.write(json.dumps({**{k: v for k, v in r.items() if k != "parsed"}, "grade": g, "labels": labels}, ensure_ascii=False, default=str) + "\n")
                print(f"[{s}] {i}/{len(qs)} {q['id']} {q['category']:30s} {'PASS' if g['passed'] else 'fail'} {','.join(labels)[:80]}")
        results[s] = metrics(rows)
        labelled[s] = lab
    return qs, results, labelled


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


def write_docs(split, results, counts, traps, examples, target_dir, model):
    stamp = time.strftime("%Y-%m-%d %H:%M")
    names = list(results)
    rows = ["accuracy", "json_valid_first_try", "json_valid_final", "band_accuracy", "recommendation_accuracy", "checklist_accuracy",
            "finding_recall", "fact_recall", "citation_hit_rate", "refusal_accuracy", "injection_resistance", "pii_leak_free",
            "calls_per_query", "tokens_per_query", "median_latency_ms"]
    t = ["## Step 1.6: Prompting baseline (single agent, single prompt, gold passages pasted in)", "",
         f"Run {stamp} · model `{model}` · eval_v1 **{split}** split · context = gold documents (retrieval not tested here).", "",
         "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in rows:
        t.append(f"| {k} | " + " | ".join(str(results[s].get(k)) for s in names) + " |")
    t += ["", "| Category | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    cats = sorted({c for s in names for c in results[s].get("by_category", {})})
    for c in cats:
        t.append(f"| {c} | " + " | ".join(results[s]["by_category"].get(c, "-") for s in names) + " |")
    t += ["", "Strategy definitions are in `app/prompting.py`; raw outputs in `runs/prompt_baseline/`. Failure analysis: `docs/failure_log.md`.", ""]
    path = target_dir / "baselines.md"
    existing = path.read_text() if path.exists() else "# Week 1 baselines\n\n"
    start = existing.find("## Step 1.6")
    if start >= 0:
        end = existing.find("\n## ", start + 5)
        existing = existing[:start] + (existing[end + 1:] if end >= 0 else "")
    head, sep, rest = existing.partition("\n## ")
    path.write_text(head.rstrip() + "\n\n" + "\n".join(t) + ("\n## " + rest if sep else "\n"))

    all_labels = sorted({l for c in counts.values() for l in c}, key=lambda l: -sum(c[l] for c in counts.values()))
    f = ["# Step 1.7: How the small model breaks (failure log)", "",
         f"Run {stamp} · model `{model}` · eval_v1 {split} split · generated by `scripts/prompt_baseline.py`, labels from `app/failure_analysis.py`.",
         "Add your own observations in the **Team notes** column; these feed the Week 3 design and the graded report section "
         "*\"What did we do to compensate for a small model?\"*.", "",
         "## Failure counts (queries affected)", "", "| Failure | " + " | ".join(names) + " | Team notes |", "|---|" + "---|" * len(names) + "---|"]
    for l in all_labels:
        f.append(f"| {l} | " + " | ".join(str(counts[s].get(l, 0)) for s in names) + " | |")
    trap_labels = sorted({l for c in traps.values() for l in c})
    if trap_labels:
        f += ["", "## Traps that caught the model", "", "| Trap | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for l in trap_labels:
            f.append(f"| {l[5:]} | " + " | ".join(str(traps[s].get(l, 0)) for s in names) + " |")
    f += ["", "## Examples", ""]
    for l in all_labels:
        for s, q, r in examples.get(l, []):
            out = json.dumps(r.get("response"), ensure_ascii=False)[:500] if r.get("response") else (r.get("raw") or [""])[-1][:500]
            f += [f"### {l} · {s} · {q['id']} ({q['category']})", "", f"- **Question:** {q['request']['question']}",
                  f"- **Expected:** {q['gold_answer'][:300]}", f"- **Got:** `{out}`", f"- **Error:** {r.get('error') or '-'}", "- **Team notes:** ", ""]
    f += ["## Mitigations to try in Weeks 2-3 (fill in the before/after numbers)", "",
          "| Failure | Mitigation | Before | After |", "|---|---|---|---|",
          "| JSON_INVALID / JSON_NEEDED_RETRY | Smaller per-call schemas; constrained decoding if the endpoint supports it; repair retry | | |",
          "| SCORE_ARITHMETIC / WRONG_BAND | Scores computed by the deterministic engine tool, never by the LLM | | |",
          "| MISSING_AS_COMPLIANT / EXPIRED_AS_VALID | compliance_checker tool computes statuses from dates; LLM only explains | | |",
          "| INJECTION_* | Delimit retrieved text as data; strip instruction-like lines; critic checks verdict against tool output | | |",
          "| INVENTED_CITATION | Critic verifies every cited id is in the retrieved set | | |",
          "| MISSED_REFUSAL / OVER_REFUSAL | Rule-based pre-classifier for approval/sign/PII/secrets before the LLM | | |", ""]
    (target_dir / "failure_log.md").write_text("\n".join(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    mock = llm_client.backend() == "mock"
    import os
    model = "mock" if mock else os.environ.get("LLM_MODEL", "?")
    out_dir = ROOT / "runs" / "prompt_baseline" / (("mock_" if mock else "") + time.strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    qs, results, labelled = run(a.strategies.split(","), a.split, a.limit, out_dir)
    counts, traps, examples = summarise(labelled)
    report = dict(model=model, backend=llm_client.backend(), split=a.split, queries=len(qs), results=results,
                  failure_counts={s: dict(c) for s, c in counts.items()}, trap_failures={s: dict(c) for s, c in traps.items()}, raw_dir=str(out_dir.relative_to(ROOT)))
    rep_dir = ROOT / "reports" / ("mock" if mock else "")
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "prompt_baseline_v1.json").write_text(json.dumps(report, indent=1))
    write_docs(a.split, results, counts, traps, examples, rep_dir if mock else ROOT / "docs", model)
    print(json.dumps({s: {k: v for k, v in r.items() if k != "by_category"} for s, r in results.items()}, indent=1))
    if mock:
        print("\nMOCK RUN: numbers are meaningless; outputs in reports/mock/ only.")


if __name__ == "__main__":
    main()
