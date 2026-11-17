# Evaluation protocol (no performance claims)

## Current release status

The project ships software tests for serialization, source normalization, citation auditing, safe material ingestion, server/queue recovery, and an end-to-end offline demonstration. These tests assess code behavior only. A deterministic retrieval-metric calculator is included, but no labelled gold-set evaluation, human evaluation, systematic review-quality assessment, or productivity study has been performed for this release.

## Retrieval benchmark input and calculation

Create a UTF-8 JSONL file with one query per line. Every record requires a unique `query_id`, a `retrieved_ids` list in ranked order (which may be empty), and a non-empty `relevant_ids` list of researcher-verified relevant identifiers. Duplicate identifiers are rejected. Prefer normalized DOI identifiers when possible; otherwise choose a stable catalogue or corpus identifier and apply the same normalization to both lists.

```json
{"query_id":"trial-01","retrieved_ids":["10.1000/a","10.1000/b"],"relevant_ids":["10.1000/b","10.1000/c"]}
{"query_id":"trial-02","retrieved_ids":[],"relevant_ids":["10.1000/d"]}
```

Run `argumentum benchmark-retrieval --input gold.jsonl --k 10 --output report.json`. The utility computes per-query and macro-mean precision@k, recall@k, mean reciprocal rank@k, nDCG@k, and hit-rate@k. Precision@k uses `k` as the denominator even when fewer than `k` records were retrieved; empty result lists therefore score zero. The tool does not validate the gold annotations or establish that a relevant title contains evidence for any particular claim.

## Suggested evaluation before research deployment

Researchers evaluating Argumentum for a specific discipline should create a held-out, manually curated benchmark with:

- a preregistered research question and explicit search protocol;
- a source corpus with stable identifiers and verified bibliographic metadata;
- expert-labelled inclusion/exclusion decisions;
- claim-to-source annotations at sentence or claim level;
- independently assessed synthesis themes and contradictions;
- a pre-specified methods audit rubric;
- a human-authored reference manuscript or accepted review as a comparison artifact;
- a disclosure of model, provider, prompt/configuration, run date, and reviewer expertise.

## Recommended measures

| Dimension | Example measure | Human validation required? |
|---|---|---|
| Retrieval | Recall@k, precision@k, DOI resolution rate, coverage by database | Yes, to establish the gold corpus. |
| Screening | Sensitivity and specificity against expert labels; reasons for exclusion | Yes. |
| Citation support | Proportion of claims whose cited full text supports the claim | Yes; identifier validity alone is insufficient. |
| Synthesis | Expert agreement on themes, contradictions, omissions, and balance | Yes. |
| Methodology critique | Expert-rated issue relevance, severity, and missed threats | Yes. |
| Writing | Completeness, clarity, factual error rate, revision burden | Yes. |
| Reliability | Failure rate, malformed JSON rate, repeat-run variance, API error handling | Partial automation is possible. |
| Cost and time | End-to-end latency, tokens, provider cost, researcher time | Measure under a documented setup. |

## Experimental controls

Compare the same corpus, question, and constraints across models or workflow variants. Separate retrieval quality from generation quality. Blind human assessors to system identity where practical. Report uncertainty and disagreements. Record search dates, API versions or snapshots, model IDs, prompts, temperatures, and code commit. Do not tune on the test set and present it as held out.

## Minimum report template

1. Research question and target discipline.
2. Dataset/corpus creation and inclusion criteria.
3. Model, provider, version, and generation settings.
4. Search source, query, date, rate-limit conditions, and source count.
5. Metrics, annotation guide, assessor qualifications, and inter-rater agreement.
6. Error analysis including hallucinations, citation failures, missing evidence, and harmful overclaims.
7. Limitations, conflicts, ethics, and reproducibility artifacts.

A result from one model, discipline, or corpus should not be generalized to all research domains.
