# app/services/retrieval_service.py
from app.models.document_chunk import DocumentChunk
from app.rag.similarity import rank_chunks, rank_fusion
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
        hybrid_search: bool = False,
        rrf_k: int = 60,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._embedding_service = embedding_service
        self._top_k = top_k
        self._reranker = reranker
        self._rerank_candidates = rerank_candidates
        self._hybrid_search = hybrid_search
        self._rrf_k = rrf_k

    def retrieve(self, vehicle_id: int, question: str) -> list[tuple[DocumentChunk, float]]:
        """Embed the question, score this vehicle's chunks, return top_k.

        With both hybrid and reranker off (default) this is the original dense path, byte-identical
        to before. Otherwise a candidate pool is built — dense cosine, optionally fused with BM25
        keyword ranks via RRF — then optionally reranked, then truncated to top_k. The returned
        (chunk, cosine) tuples are only ever reordered; the float stays a cosine similarity.
        """
        candidates = self._chunk_repo.list_by_vehicle(vehicle_id)
        if not candidates:
            return []
        query_vec = self._embedding_service.embed_query(question)
        if not self._hybrid_search and self._reranker is None:
            return rank_chunks(query_vec=query_vec, chunks=candidates, top_k=self._top_k)

        cosine_scored = rank_chunks(query_vec=query_vec, chunks=candidates, top_k=len(candidates))
        if self._hybrid_search:
            bm25_ids = self._chunk_repo.search_fts(vehicle_id, question, self._rerank_candidates)
            pool = rank_fusion(cosine_scored, bm25_ids, self._rrf_k)[: self._rerank_candidates]
        else:
            pool = cosine_scored[: self._rerank_candidates]
        if self._reranker is not None:
            pool = self._reranker.rerank(question, pool)
        return pool[: self._top_k]
