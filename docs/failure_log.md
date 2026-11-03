# Step 1.7: How the small model breaks (failure log)

Not generated yet. `make prompt-baseline` (step 1.6) writes this file. It covers:
- **Failure counts** per strategy over 20+ labels (invalid JSON, injection followed, missing-as-compliant, expired-as-valid, contradiction missed, score arithmetic, invented citation, missed or over-refusal, PII leak, and more). Definitions are in `app/failure_analysis.py`.
- **Traps that caught the model:** superseded documents, future amendments, spoofed policy, and so on.
- **Two real examples per failure**, each with a **Team notes** field for M3 and M5 to annotate.
- **A mitigation table** with before/after columns. It feeds the graded report section *"What did we do to compensate for a small model?"*.

To see the format now, run `make prompt-baseline-mock` and open `reports/mock/failure_log.md` (stand-in model; numbers meaningless).
