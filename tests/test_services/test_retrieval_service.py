# tests/test_services/test_retrieval_service.py
import json
import pytest
from unittest.mock import MagicMock

from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository
from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService


@pytest.fixture
def vehicle_with_chunks(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    doc = doc_repo.create(vehicle_id=vehicle.id, file_name="manual.pdf", stored_path="/tmp/m.pdf")
    doc.processing_status = "ready"
    db_session.flush()

    chunk_repo = ChunkRepository(db_session)
    chunk_repo.bulk_create([
        DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1,
                      content="Torque spec 129 Nm", embedding_json=json.dumps([1.0, 0.0, 0.0])),
        DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2,
                      content="Minimum rotor thickness 20mm", embedding_json=json.dumps([0.0, 1.0, 0.0])),
    ])
    db_session.flush()
    return vehicle


def test_retrieve_returns_top_k_ranked_by_similarity(db_session, vehicle_with_chunks):
    vehicle = vehicle_with_chunks
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_query.return_value = [1.0, 0.0, 0.0]  # closest to chunk 0

    svc = RetrievalService(ChunkRepository(db_session), mock_embedding, top_k=1)
    results = svc.retrieve(vehicle_id=vehicle.id, question="What is the torque spec?")

    assert len(results) == 1
    chunk, score = results[0]
    assert "129 Nm" in chunk.content
    assert score == pytest.approx(1.0)


def test_retrieve_returns_empty_when_no_chunks(db_session):
    vehicle = VehicleRepository(db_session).create(year=2019, make="GM", model="Sierra", engine="5.3L")
    db_session.flush()

    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_query.return_value = [1.0, 0.0]

    svc = RetrievalService(ChunkRepository(db_session), mock_embedding, top_k=5)
    results = svc.retrieve(vehicle_id=vehicle.id, question="Any question")
    assert results == []
    mock_embedding.embed_query.assert_not_called()


class _ReverseReranker:
    """Test double: reverses the candidate order and records the pool it was handed."""

    def __init__(self):
        self.received = None

    def rerank(self, query, scored):
        self.received = scored
        return list(reversed(scored))


def test_retrieve_default_reranker_is_byte_identical_to_dense(db_session, vehicle_with_chunks):
    vehicle = vehicle_with_chunks
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_query.return_value = [1.0, 0.0, 0.0]

    svc = RetrievalService(ChunkRepository(db_session), mock_embedding, top_k=2)
    results = svc.retrieve(vehicle_id=vehicle.id, question="q")

    assert [c.content for c, _ in results] == ["Torque spec 129 Nm", "Minimum rotor thickness 20mm"]
    assert [s for _, s in results] == [pytest.approx(1.0), pytest.approx(0.0)]


def test_retrieve_applies_reranker_order_and_keeps_cosine(db_session, vehicle_with_chunks):
    vehicle = vehicle_with_chunks
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_query.return_value = [1.0, 0.0, 0.0]  # dense: chunk0 (1.0) before chunk1 (0.0)

    reranker = _ReverseReranker()
    svc = RetrievalService(ChunkRepository(db_session), mock_embedding, top_k=2,
                           reranker=reranker, rerank_candidates=40)
    results = svc.retrieve(vehicle_id=vehicle.id, question="q")

    # reranker reversed the order, but each chunk still carries its own cosine
    assert [c.content for c, _ in results] == ["Minimum rotor thickness 20mm", "Torque spec 129 Nm"]
    assert [s for _, s in results] == [pytest.approx(0.0), pytest.approx(1.0)]


def test_retrieve_expands_pool_beyond_top_k_then_slices(db_session, vehicle_with_chunks):
    vehicle = vehicle_with_chunks
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_query.return_value = [1.0, 0.0, 0.0]

    reranker = _ReverseReranker()
    svc = RetrievalService(ChunkRepository(db_session), mock_embedding, top_k=1,
                           reranker=reranker, rerank_candidates=40)
    results = svc.retrieve(vehicle_id=vehicle.id, question="q")

    assert len(reranker.received) == 2  # reranker saw the expanded pool, not just top_k=1
    assert len(results) == 1            # final result sliced back to top_k
