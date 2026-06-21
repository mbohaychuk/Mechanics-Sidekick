"""Cross-encoder reranker seam, mirroring the LLM/embedding provider seam in llm_factory.

The reranker only *reorders* the dense top-N candidates — it returns a permutation of the
input `(chunk, cosine)` tuples, never a new score. That keeps the returned float a cosine
similarity, so every consumer (the diagnostic web-fallback gate, the search_manuals tool
display) is unaffected. `flashrank` is imported lazily so the base install never pulls
onnxruntime and the hermetic test suite never touches it.
"""
from __future__ import annotations

from typing import Protocol

from app.models.document_chunk import DocumentChunk

Scored = list[tuple[DocumentChunk, float]]


def _enriched_text(chunk: DocumentChunk) -> str:
    """Reconstruct the text that was embedded (context + section + content), so the
    cross-encoder scores against the same contextual signal, not just the raw chunk."""
    head = "\n".join(p for p in (chunk.context_summary, chunk.section_title) if p)
    return f"{head}\n\n{chunk.content}" if head else chunk.content


class Reranker(Protocol):
    def rerank(self, query: str, scored: Scored) -> Scored:
        """Return the same (chunk, cosine) tuples reordered by query relevance."""
        ...


class NoOpReranker:
    """Default: identity — the dense cosine order is left untouched."""

    def rerank(self, query: str, scored: Scored) -> Scored:
        return scored


class FlashRankReranker:
    def __init__(self, model: str) -> None:
        from flashrank import Ranker, RerankRequest  # lazy: keeps onnxruntime out of the base install

        self._RerankRequest = RerankRequest
        self._ranker = Ranker(model_name=model)

    def rerank(self, query: str, scored: Scored) -> Scored:
        if len(scored) < 2:
            return scored
        passages = [{"id": i, "text": _enriched_text(chunk)} for i, (chunk, _score) in enumerate(scored)]
        ranked = self._ranker.rerank(self._RerankRequest(query=query, passages=passages))
        return [scored[entry["id"]] for entry in ranked]
