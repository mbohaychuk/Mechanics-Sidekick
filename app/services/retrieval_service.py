# app/services/retrieval_service.py
from app.models.document_chunk import DocumentChunk
from app.rag.similarity import rank_chunks
from app.repositories.chunk_repository import ChunkRepository
from app.services.embedding_service import EmbeddingService
from app.services.reranker import Reranker


class RetrievalService:
    def __init__(
        self,
        chunk_repo: ChunkRepository,
        embedding_service: EmbeddingService,
        top_k: int = 5,
        reranker: Reranker | None = None,
        rerank_candidates: int = 40,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._embedding_service = embedding_service
        self._top_k = top_k
        self._reranker = reranker
        self._rerank_candidates = rerank_candidates

    def retrieve(self, vehicle_id: int, question: str) -> list[tuple[DocumentChunk, float]]:
        """Embed the question, score all vehicle chunks, return top_k.

        With no reranker (default) this is the original dense path. With one, a wider dense
        candidate pool is reranked by query relevance, then truncated to top_k — the returned
        (chunk, cosine) tuples are unchanged, only reordered.
        """
        candidates = self._chunk_repo.list_by_vehicle(vehicle_id)
        if not candidates:
            return []
        query_vec = self._embedding_service.embed_query(question)
        if self._reranker is None:
            return rank_chunks(query_vec=query_vec, chunks=candidates, top_k=self._top_k)
        pool = rank_chunks(query_vec=query_vec, chunks=candidates, top_k=self._rerank_candidates)
        return self._reranker.rerank(question, pool)[: self._top_k]
