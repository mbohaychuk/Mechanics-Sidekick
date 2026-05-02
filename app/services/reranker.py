# app/services/reranker.py
"""Reranker abstraction.

The hybrid retrieval pipeline pulls top-30 candidates fast (FTS5 + vec0).
A reranker rescores those 30 with a cross-encoder for higher precision and
returns the top-10. Production uses BgeReranker (BAAI/bge-reranker-v2-m3);
unit tests use IdentityReranker to stay offline.
"""
from typing import Protocol

from app.models.document_chunk import DocumentChunk


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        """Return chunks rescored against the query, sorted descending, len <= top_k."""
        ...


class IdentityReranker:
    """No-op reranker: preserves input order, scores all 1.0. For tests."""

    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        return [(c, 1.0) for c in candidates[:top_k]]


class BgeReranker:
    """Cross-encoder reranker backed by sentence-transformers.

    The model is loaded lazily on first rerank() call (or at construction if
    a cross_encoder is injected). Scores `[query, chunk.content]` pairs in a
    single batch.
    """

    def __init__(
        self,
        model_name: str,
        cross_encoder=None,
    ) -> None:
        self._model_name = model_name
        self._ce = cross_encoder

    def _load(self):
        if self._ce is None:
            from sentence_transformers import CrossEncoder
            self._ce = CrossEncoder(self._model_name)
        return self._ce

    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not candidates:
            return []
        ce = self._load()
        pairs = [(query, c.content) for c in candidates]
        scores = ce.predict(pairs)
        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(c, float(s)) for c, s in scored[:top_k]]
