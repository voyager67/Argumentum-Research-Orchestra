"""Deterministic information-retrieval metrics for researcher-labelled gold sets."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


class BenchmarkInputError(ValueError):
    """A retrieval benchmark file is malformed or ambiguous."""


def _unique_string_list(value: Any, field: str, query_id: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        expectation = "a list" if allow_empty else "a non-empty list"
        raise BenchmarkInputError(f"{field} for query {query_id!r} must be {expectation} of strings")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BenchmarkInputError(f"{field} for query {query_id!r} contains a blank or non-string identifier")
        values.append(item.strip())
    if len(values) != len(set(values)):
        raise BenchmarkInputError(f"{field} for query {query_id!r} contains duplicate identifiers")
    return values


def score_retrieval_query(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> dict[str, float | int]:
    """Compute binary-relevance P@k, R@k, MRR@k, nDCG@k and hit-rate@k."""
    if k < 1:
        raise ValueError("k must be at least 1")
    if len(retrieved_ids) != len(set(retrieved_ids)):
        raise ValueError("retrieved_ids contains duplicates")
    if not relevant_ids:
        raise ValueError("relevant_ids must contain at least one gold identifier")
    if len(relevant_ids) != len(set(relevant_ids)):
        raise ValueError("relevant_ids contains duplicates")

    top = retrieved_ids[:k]
    relevant = set(relevant_ids)
    hits = [rank for rank, item in enumerate(top, start=1) if item in relevant]
    precision = len(hits) / k
    recall = len(hits) / len(relevant)
    reciprocal_rank = 1.0 / hits[0] if hits else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in hits)
    ideal_hits = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return {
        f"precision@{k}": precision,
        f"recall@{k}": recall,
        f"mrr@{k}": reciprocal_rank,
        f"ndcg@{k}": dcg / idcg if idcg else 0.0,
        f"hit_rate@{k}": 1.0 if hits else 0.0,
        "retrieved_count": len(retrieved_ids),
        "relevant_count": len(relevant_ids),
        "hits_in_top_k": len(hits),
    }


def load_benchmark_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_query_ids: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkInputError(f"Invalid JSON on line {line_number}") from exc
        if not isinstance(payload, dict):
            raise BenchmarkInputError(f"Line {line_number} must contain a JSON object")
        query_id = payload.get("query_id")
        if not isinstance(query_id, str) or not query_id.strip():
            raise BenchmarkInputError(f"Line {line_number} requires a non-empty query_id")
        query_id = query_id.strip()
        if query_id in seen_query_ids:
            raise BenchmarkInputError(f"Duplicate query_id {query_id!r}")
        seen_query_ids.add(query_id)
        rows.append(
            {
                "query_id": query_id,
                "retrieved_ids": _unique_string_list(
                    payload.get("retrieved_ids"), "retrieved_ids", query_id, allow_empty=True
                ),
                "relevant_ids": _unique_string_list(
                    payload.get("relevant_ids"), "relevant_ids", query_id, allow_empty=False
                ),
            }
        )
    if not rows:
        raise BenchmarkInputError("Benchmark file contains no query records")
    return rows


def evaluate_retrieval_jsonl(path: str | Path, k: int = 5) -> dict[str, Any]:
    if k < 1 or k > 100:
        raise ValueError("k must be between 1 and 100")
    rows = load_benchmark_jsonl(path)
    per_query = []
    for row in rows:
        metrics = score_retrieval_query(row["retrieved_ids"], row["relevant_ids"], k)
        per_query.append({"query_id": row["query_id"], **metrics})
    metric_keys = [f"precision@{k}", f"recall@{k}", f"mrr@{k}", f"ndcg@{k}", f"hit_rate@{k}"]
    macro = {key: mean(float(row[key]) for row in per_query) for key in metric_keys}
    return {
        "benchmark_type": "retrieval_binary_relevance",
        "k": k,
        "query_count": len(per_query),
        "aggregation": "macro_mean_over_queries",
        "metrics": macro,
        "per_query": per_query,
        "interpretation": "Metrics are meaningful only relative to the supplied researcher-labelled gold set; they do not assess evidence entailment or scientific correctness.",
    }
