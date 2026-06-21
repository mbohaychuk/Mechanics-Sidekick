"""Runs golden questions through RetrievalService.retrieve() and aggregates the metrics.

Relevance is decided per retrieved chunk by either a content substring match (robust for
DTC codes / spec values, and stable across re-chunking) or a page-cluster match (for
multi-page procedures), so the harness keeps measuring the same target as chunking changes.
Splits into pure pieces + a thin orchestrator so the logic unit-tests with no DB.
"""
import re
from collections.abc import Sequence

from evals.metrics import hit_at_k, reciprocal_rank


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def chunk_is_relevant(chunk, answer_contains: Sequence[str], relevant_pages: Sequence[int]) -> bool:
    """Relevant if the chunk's content contains any answer string, or its page is in the cluster."""
    content = _norm(getattr(chunk, "content", "") or "")
    if any(_norm(a) in content for a in answer_contains):
        return True
    page = getattr(chunk, "page_number", None)
    return page is not None and page in set(relevant_pages)


def relevance_flags(results: Sequence, answer_contains: Sequence[str], relevant_pages: Sequence[int]) -> list[bool]:
    return [chunk_is_relevant(chunk, answer_contains, relevant_pages) for chunk, _score in results]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rollup(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "mrr": _mean([r["reciprocal_rank"] for r in rows]),
        "hit_rate": _mean([1.0 if r["hit"] else 0.0 for r in rows]),
        "hit_rate_at_1": _mean([1.0 if r["hit1"] else 0.0 for r in rows]),
    }


def summarize(per_question: list[dict]) -> dict:
    """Overall hit-rate + MRR plus a per-type (exact_token / conceptual) breakdown."""
    summary = _rollup(per_question)
    by_type: dict[str, list[dict]] = {}
    for row in per_question:
        by_type.setdefault(row["type"], []).append(row)
    summary["by_type"] = {t: _rollup(rows) for t, rows in by_type.items()}
    return summary


def run_eval(retrieval_service, vehicle_id: int, questions: list[dict], k: int) -> dict:
    """Score every golden question through retrieve() and return per-question + summary."""
    per_question: list[dict] = []
    for q in questions:
        results = retrieval_service.retrieve(vehicle_id, q["question"])
        flags = relevance_flags(results, q.get("answer_contains", []), q.get("relevant_pages", []))
        per_question.append({
            "id": q["id"],
            "type": q.get("type", "conceptual"),
            "hit": hit_at_k(flags, k),
            "hit1": hit_at_k(flags, 1),
            "reciprocal_rank": reciprocal_rank(flags),
        })
    return {"summary": summarize(per_question), "per_question": per_question}
