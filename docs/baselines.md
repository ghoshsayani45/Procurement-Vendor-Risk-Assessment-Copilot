# Week 1 baselines

Recorded before any agent code, as the Week 1 gate requires. Re-run any section with the commands below; each script rewrites only its own section.

| Step | Status | Command |
|---|---|---|
| 1.6 Prompting strategies | **Done** (Qwen3-8B, 2026-11-08; results below) | `make prompt-baseline` (all 3 strategies, dev split) |
| 1.7 Failure log | **Done** → `docs/failure_log.md` | (same) |
| 1.8 Retrieval: BM25 | **Done** (results below) | `make retrieval-baseline` |
| 1.8 Retrieval: dense | **Waiting for the embeddings endpoint** | `make retrieval-baseline RETRIEVERS=bm25,dense` |

Before the real run, check the pipeline offline with `make prompt-baseline-mock`. It uses a deliberately weak stand-in model; its numbers mean nothing and go to `reports/mock/` only.

## Step 1.6: Prompting baseline (single agent, single prompt, gold passages pasted in)

Model `Qwen/Qwen3-8B` · eval_v1 **dev** split · context = gold documents (retrieval not tested here).
Runs: `structured_fewshot` 2026-11-08 00:30 (30 queries); `cot_sc` 2026-11-08 00:39 (30 queries); `decomposition` 2026-11-08 13:05 (30 queries).

| Metric | structured_fewshot | cot_sc | decomposition |
|---|---|---|---|
| accuracy | 0.5 | 0.533 | 0.5 |
| json_valid_first_try | 0.967 | 0.9 | 0.967 |
| json_valid_final | 1.0 | 1.0 | 1.0 |
| band_accuracy | 0.429 | 0.429 | 0.429 |
| recommendation_accuracy | 0.286 | 0.286 | 0.571 |
| checklist_accuracy | 0.794 | 0.851 | 0.595 |
| finding_recall | 0.136 | 0.136 | 0.119 |
| fact_recall | 0.662 | 0.725 | 0.775 |
| citation_hit_rate | 1.0 | 1.0 | 1.0 |
| refusal_accuracy | 1.0 | 1.0 | 1.0 |
| injection_resistance | 0.0 | 0.0 | 0.0 |
| pii_leak_free | 1.0 | 1.0 | 1.0 |
| calls_per_query | 1.03 | 3.2 | 2.03 |
| tokens_per_query | 4675 | 14909 | 8403 |
| median_latency_ms | 1856 | 6039 | 12164 |

| Category | structured_fewshot | cot_sc | decomposition |
|---|---|---|---|
| adversarial | 0/2 | 0/2 | 1/2 |
| clarify | 2/2 | 2/2 | 0/2 |
| comparison | 0/2 | 0/2 | 0/2 |
| external_regulation | 2/3 | 2/3 | 3/3 |
| full_review | 0/7 | 0/7 | 0/7 |
| internal_policy | 3/3 | 3/3 | 3/3 |
| lookup_vendor | 4/5 | 5/5 | 5/5 |
| missing_conflicting_evidence | 1/3 | 1/3 | 0/3 |
| refusal | 3/3 | 3/3 | 3/3 |

Strategy definitions are in `app/prompting.py`; raw outputs in `runs/prompt_baseline/`. Failure analysis: `docs/failure_log.md` (generated) and `docs/failure_notes.md` (team notes).

**Headline.** With the right documents pasted into the prompt, Qwen3-8B answers about **half** of the dev queries correctly under every strategy (50.0%, 53.3%, 50.0%). It fails **every full review (0/7)** and **every comparison (0/2)**, and **never detects** a prompt injection (0%); it follows the injected instruction under two of the three strategies. Prompting strategy changes the cost far more than the quality.

### What a single prompt can and cannot do

| Works (single-fact reading) | Fails (multi-rule synthesis) |
|---|---|
| Vendor fact lookups: 4/5 to 5/5 | Full reviews: 0/7 for all strategies |
| Internal policy questions: 3/3 | Risk band correct: 43% for all strategies |
| External regulation: 2/3 to 3/3 | Planted findings recalled: 12–14% (≈ 6 in 7 issues missed) |
| Refusals: 3/3, correct category every time | Comparisons: 0/2 (inherits the band errors) |
| Citations to a real gold document: 100% | Missing/conflicting evidence: 0/3 to 1/3 |
| No personal data leaked: 100% | Prompt injection detected: 0% (followed in 2 of 3 strategies) |

The model reads individual facts well. It breaks down when it has to apply many policy rules at once: tier, required evidence, validity dates, points, weights, bands, knockouts and approvers. The failure log makes this concrete: SCORE_ARITHMETIC and MISSED_FINDINGS hit **7 of 7** full reviews, WRONG_APPROVERS 6–7 of 7 and WRONG_BAND 6 of 7, **identically for all three strategies**.

### Strategy comparison

| | Structured few-shot | CoT + self-consistency (3 samples) | Decomposition |
|---|---|---|---|
| Accuracy | 50.0% | **53.3%** | 50.0% |
| Checklist accuracy | 79% | **85%** | 60% |
| Recommendation correct | 29% | 29% | **57%** |
| Fact recall (questions) | 66% | 73% | **78%** |
| Clarify when ambiguous | 2/2 | 2/2 | **0/2** |
| Followed the injection (EVAL-007) | yes | yes | no (but not flagged) |
| Tokens per query | **4.7k** | 14.9k (3.2×) | 8.4k (1.8×) |
| Median latency | **1.9 s** | 6.0 s | 12.2 s |

- **Structured few-shot is the best value:** within one query of the best accuracy, at the lowest cost and latency.
- **Self-consistency** buys a better checklist (+6 points) for 3.2× the tokens, but no gain on band, findings or injections.
- **Decomposition** helps where reasoning is sequential (recommendation, multi-part facts) and was the only strategy not to follow the injection, but it hurts the checklist. It also stops asking clarifying questions: splitting the task into sub-questions pushes the model to answer.

### Format lessons (what it took to get 97–100% valid JSON)

1. **One answer shape per call, stated last.** The model picks its shape from the question's topic, not from `REQUEST_KIND`, unless the shape is the final instruction (EVAL-047 before the fix).
2. **Fit the serving limits.** The course gateway allows 8,192 context tokens and 1,024 answer tokens. The full report JSON did not fit, so full reviews use a compact format that is expanded before grading (D16).
3. **Give the vocabulary.** Without the list of finding codes, the model invents codes (`F001`, `…-VERIFIED`).
4. **Expect paraphrased labels.** Under decomposition it copies the policy's wording ("Escalate (high risk)", "PRESENT"). These are normalised before grading, so substance is judged, not spelling (D17).

### What this means for Weeks 2–3

| Finding | Design response |
|---|---|
| Band 43%, scores wrong, findings 12–14% | Checklist, score, band and approvers come from the deterministic `compliance_checker` / `financial_risk_calculator` tools (rubric engine); the LLM only explains |
| Missing vs. required confused (EVAL-039) | Evidence status from the vendor's records via `vendor_search`, not from reading the policy |
| Date and number comparisons wrong | All date and threshold comparisons in code |
| Injection never detected (followed in 2 of 3 strategies) | Retrieved text delimited as data, instruction-like lines stripped, critic checks the verdict against tool output, injection attempts logged |
| Shape and vocabulary errors | One small schema per agent node; enums and code lists in every prompt; constrained decoding if the endpoint supports it |
| Few-shot ≈ self-consistency at a third of the cost | Default agent prompts use structured few-shot; self-consistency only for a single high-stakes field, if at all |

### Caveats

- **Small sample:** 30 dev queries, of which 7 are full reviews, so one query is worth 3.3 points.
- **One model** (Qwen3-8B), with thinking mode disabled.
- **Retrieval excluded:** gold documents were pasted in, so these are upper-bound conditions for the model's reasoning.
- **Test split untouched:** its 50 queries are reserved for the Week 3 and Week 4 gates.


## Step 1.8: Retrieval baselines

Run 2026-11-03 09:44 on corpus v1 (1053 documents → 5663 fixed 512-token chunks, 64-token overlap). Document-level metrics on eval_v1 queries that have gold documents; the query is the user's raw question (no rewriting).

### bm25: dev split

| Category | n | hit@5 | hit@10 | recall@5 | recall@10 | recall@20 | MRR |
|---|---|---|---|---|---|---|---|
| **ALL** | 26 | 0.885 | 0.885 | 0.569 | 0.678 | 0.824 | 0.707 |
| adversarial | 2 | 1.0 | 1.0 | 0.75 | 0.75 | 0.75 | 1.0 |
| comparison | 2 | 1.0 | 1.0 | 0.179 | 0.322 | 0.622 | 0.75 |
| external_regulation | 3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.333 | 0.05 |
| full_review | 7 | 1.0 | 1.0 | 0.347 | 0.568 | 0.813 | 0.786 |
| internal_policy | 3 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| lookup_vendor | 5 | 1.0 | 1.0 | 0.9 | 1.0 | 1.0 | 0.84 |
| missing_conflicting_evidence | 3 | 1.0 | 1.0 | 0.667 | 0.833 | 1.0 | 0.344 |
| refusal | 1 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

### bm25: test split

| Category | n | hit@5 | hit@10 | recall@5 | recall@10 | recall@20 | MRR |
|---|---|---|---|---|---|---|---|
| **ALL** | 44 | 0.932 | 0.955 | 0.636 | 0.775 | 0.869 | 0.808 |
| adversarial | 4 | 1.0 | 1.0 | 0.875 | 1.0 | 1.0 | 1.0 |
| comparison | 4 | 1.0 | 1.0 | 0.149 | 0.274 | 0.427 | 1.0 |
| external_regulation | 5 | 0.6 | 0.8 | 0.6 | 0.8 | 0.8 | 0.504 |
| full_review | 11 | 1.0 | 1.0 | 0.309 | 0.589 | 0.865 | 0.803 |
| internal_policy | 5 | 1.0 | 1.0 | 0.9 | 0.9 | 1.0 | 1.0 |
| lookup_vendor | 9 | 1.0 | 1.0 | 0.944 | 1.0 | 1.0 | 0.759 |
| missing_conflicting_evidence | 5 | 0.8 | 0.8 | 0.7 | 0.8 | 0.8 | 0.672 |
| refusal | 1 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

### dense

Not run: embeddings endpoint not configured: set EMBED_BASE_URL / EMBED_MODEL in .env, or run on a laptop with EMBED_BACKEND=local (downloads BAAI/bge-small-en-v1.5)

### External check: ACORD clause retrieval (BM25)

57 test-split attorney queries over 3,931 CUAD clauses with expert 1–5 star labels (qrels 0–4): NDCG@5 **0.066**, NDCG@10 **0.087**, recall@10 of 3+ star clauses **0.086**. ACORD queries are short legal phrases (e.g. 'Audit Rights') with ~10 relevant clauses each among thousands of near-misses from the same category; lexical overlap alone ranks those near-misses as high as the relevant clauses. This is the case for dense retrieval plus a reranker.

### Reading these numbers

- Full reviews have about 10 gold documents each, so recall@k is low by construction; hit@k is the fairer view for them. A single question cannot retrieve a whole review package, which is why the Week 3 agent retrieves per checklist item.
- Low recall on vendor questions usually means the right vendor's documents are outranked by look-alike documents from other vendors (all synthetic vendors share templates). Metadata filtering by `vendor_id` (Week 2) is the expected fix.
- The worst queries for each retriever are listed under `worst_queries` in `reports/retrieval_baseline_v1.json`.

## Step 1.8: Key observations (team notes)

1. **BM25 is a strong start on vendor-specific questions.** hit@10 is 1.0 for lookups, full reviews and internal policy, because vendor names are rare tokens that pin the right documents.
2. **Primary sources lose to documents that restate them.** All four external-regulation misses at hit@10 follow this pattern:
    - The DPDP questions (EVAL-055, EVAL-056) retrieve the internal Data Protection Standard (`POLICY-DPS-004`), which paraphrases the Act and Rules.
    - The GFR questions (EVAL-058, EVAL-059) retrieve the procurement manuals, which restate GFR rules, instead of GFR itself.

   The answer may still be right, but it cites a secondary source. Week 2 fix: boost primary sources by source type, or search policy and regulation as separate pools.
3. **Superseded documents surface.** For EVAL-058 the top hit is the superseded 2022 Goods Manual. The 2024 Goods Manual question (EVAL-060) is retrieved correctly at rank 1. Week 2 fix: down-weight or filter `status = SUPERSEDED`, or drop `POL-002` (see the corpus notes).
4. **Comparisons and full reviews need many documents** (about 10 per vendor), so one query can't recall them all: recall@10 is 0.27–0.59. This argues for per-checklist-item retrieval with a `vendor_id` filter in the Week 3 agent, not one big search.
5. **Generic text outranks the vendor's own evidence.** "Does Passgrove enforce MFA?" (EVAL-042) returns CCM guidance chunks about MFA before Passgrove's CAIQ and pentest. "Has Recoverly given us a DR test?" (EVAL-045) returns other vendors' documents, because the evidence doesn't exist. Two fixes: a `vendor_id` filter whenever the request names a vendor, and confirming absence through a metadata lookup (the `vendor_search` / `compliance_checker` tools), not retrieval.
6. **ACORD shows the limit of lexical matching on legal clauses.** Short attorney queries such as "Audit Rights" give NDCG@5 of 0.07, because thousands of same-category clauses share the keywords. Dense retrieval plus a cross-encoder reranker (Week 2) should be judged on this benchmark too.
