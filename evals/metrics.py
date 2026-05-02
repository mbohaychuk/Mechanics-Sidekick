# evals/metrics.py
"""Aggregate per-entry result records into pass@1 + source metrics."""
from collections import defaultdict
from statistics import mean


def compute_metrics(records: list[dict]) -> dict:
    """Aggregate result records produced by the eval runner.

    Each record contains:
        id, failure_mode, passed, iterations, latency_s, sources,
        expected_source_pdf, expected_source_pages

    Returns a dict with overall + per-failure-mode breakdowns.
    """
    if not records:
        return {
            "overall": {
                "count": 0,
                "pass_at_1": 0.0,
                "mean_iterations": 0.0,
                "mean_latency_s": 0.0,
                "source_page_precision": None,
                "source_page_recall": None,
            },
            "by_failure_mode": {},
        }

    overall = _aggregate_one("overall", records)

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_mode[r["failure_mode"]].append(r)

    by_failure_mode = {mode: _aggregate_one(mode, recs) for mode, recs in by_mode.items()}

    return {"overall": overall, "by_failure_mode": by_failure_mode}


def _aggregate_one(label: str, records: list[dict]) -> dict:
    count = len(records)
    pass_at_1 = sum(1 for r in records if r["passed"]) / count
    mean_iter = mean(r["iterations"] for r in records)
    mean_latency = mean(r["latency_s"] for r in records)

    source_relevant = [r for r in records if r.get("expected_source_pdf")]
    if source_relevant:
        precisions = []
        recalls = []
        for r in source_relevant:
            expected_pairs = {(r["expected_source_pdf"], p) for p in r["expected_source_pages"]}
            returned_pairs = {(s["filename"], s["page"]) for s in r["sources"] if s.get("page") is not None}
            if returned_pairs:
                precisions.append(len(expected_pairs & returned_pairs) / len(returned_pairs))
            else:
                precisions.append(0.0)
            if expected_pairs:
                recalls.append(len(expected_pairs & returned_pairs) / len(expected_pairs))
            else:
                recalls.append(0.0)
        page_precision = mean(precisions) if precisions else None
        page_recall = mean(recalls) if recalls else None
    else:
        page_precision = None
        page_recall = None

    return {
        "count": count,
        "pass_at_1": pass_at_1,
        "mean_iterations": mean_iter,
        "mean_latency_s": mean_latency,
        "source_page_precision": page_precision,
        "source_page_recall": page_recall,
    }
