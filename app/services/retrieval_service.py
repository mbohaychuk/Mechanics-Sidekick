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

    def retrieve(
        self, vehicle_id: int, question: str, mode: str = "auto"
    ) -> list[tuple[DocumentChunk, float]]:
        """Embed the question, score this vehicle's chunks, return top_k.

        `mode` is query-adaptive routing (set by the agent from the user's intent): a `"lookup"`
        query (a spec / value / code) skips the cross-encoder reranker, which is semantic and buries
        lexically-exact spec/table matches; a `"procedure"` (or default `"auto"`) query is reranked,
        which is where the cross-encoder helps. The returned (chunk, cosine) tuples are only ever
        reordered; the float stays a cosine similarity.
        """
        candidates = self._chunk_repo.list_by_vehicle(vehicle_id)
        if not candidates:
            return []
        query_vec = self._embedding_service.embed_query(question)
        apply_rerank = self._reranker is not None and mode != "lookup"
        if not self._hybrid_search and not apply_rerank:
            return rank_chunks(query_vec=query_vec, chunks=candidates, top_k=self._top_k)

        cosine_scored = rank_chunks(query_vec=query_vec, chunks=candidates, top_k=len(candidates))
        if self._hybrid_search:
            bm25_ids = self._chunk_repo.search_fts(vehicle_id, question, self._rerank_candidates)
            pool = rank_fusion(cosine_scored, bm25_ids, self._rrf_k)[: self._rerank_candidates]
        else:
            pool = cosine_scored[: self._rerank_candidates]
        if apply_rerank:
            pool = self._reranker.rerank(question, pool)
        return pool[: self._top_k]
