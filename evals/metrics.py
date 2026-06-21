"""Pure retrieval-quality metrics for the RAG eval harness.

Operate on a per-rank relevance flag sequence (one bool per retrieved chunk, in rank order),
so they are independent of how relevance is decided (content match or page) and of the corpus
chunking — which lets the same golden set compare baseline vs. each retrieval phase fairly.
"""
from collections.abc import Sequence


def hit_at_k(relevance: Sequence[bool], k: int) -> bool:
    """True if any of the top-k retrieved chunks is relevant."""
    if k <= 0:
        raise ValueError("k must be positive")
    return any(relevance[:k])


def reciprocal_rank(relevance: Sequence[bool]) -> float:
    """1 / (1-based rank of the first relevant chunk); 0.0 if none are relevant."""
    for index, relevant in enumerate(relevance):
        if relevant:
            return 1.0 / (index + 1)
    return 0.0
