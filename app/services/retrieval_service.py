from app.rag.similarity import rank_chunks
from app.repositories.chunk_repository import ChunkRepository
from app.services.embedding_service import EmbeddingService


class RetrievalService:
    def __init__(
        self,
        chunk_repo: ChunkRepository,
        embedding_service: EmbeddingService,
        top_k: int = 5,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._embedding_service = embedding_service
        self._top_k = top_k

    def retrieve(self, vehicle_id: int, question: str) -> list[tuple]:
        """Embed the question, score all vehicle chunks, return top_k."""
        candidates = self._chunk_repo.list_by_vehicle(vehicle_id)
        if not candidates:
            return []
        query_vec = self._embedding_service.embed_query(question)
        return rank_chunks(query_vec=query_vec, chunks=candidates, top_k=self._top_k)
