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
