# tests/test_services/test_hybrid_retrieval_service.py
import pytest
from unittest.mock import MagicMock

from app.models.document_chunk import DocumentChunk
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_retrieval_service import HybridRetrievalService


@pytest.fixture
def vehicle_with_corpus(db_session):
    """Insert two vehicles (to test scoping) and a tiny chunk corpus."""
    v1 = VehicleRepository(db_session).create(year=2006, make="Audi", model="A8", engine="4.2L V8")
    v2 = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L V8")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    doc1 = doc_repo.create(v1.id, "audi.pdf", "/tmp/a.pdf")
    doc1.processing_status = "ready"
    doc2 = doc_repo.create(v2.id, "ford.pdf", "/tmp/f.pdf")
    doc2.processing_status = "ready"
    db_session.flush()

    repo = ChunkRepository(db_session)
    repo.bulk_create([
        # Audi chunks — chunk_id 1..3
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=0, page_number=1,
                                content="Cylinder head bolt torque is 129 Nm"),
            indexable_text="Cylinder head bolt torque 129 Nm 4.2L V8 Audi",
            embedding=[1.0, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=1, page_number=2,
                                content="Wheel bolt torque 120 Nm diagonal pattern"),
            indexable_text="Wheel bolt torque 120 Nm diagonal pattern Audi",
            embedding=[0.0, 1.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=2, page_number=3,
                                content="Brake fluid DOT 4 specification"),
            indexable_text="Brake fluid DOT 4 specification Audi",
            embedding=[0.0, 0.0, 1.0, 0.0],
        ),
        # Ford chunk — chunk_id 4 — must NOT be returned for vehicle=v1.
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc2.id, chunk_index=0, page_number=1,
                                content="Cylinder head bolt torque is 95 Nm"),
            indexable_text="Cylinder head bolt torque 95 Nm 5.0L V8 Ford F-150",
            embedding=[0.9, 0.1, 0.0, 0.0],  # very close to query — vector match
        ),
    ])
    db_session.flush()
    return v1, v2


def _make_service(db_session, query_embedding=None) -> HybridRetrievalService:
    embedding = MagicMock(spec=EmbeddingService)
    embedding.embed_query.return_value = query_embedding or [1.0, 0.0, 0.0, 0.0]
    return HybridRetrievalService(
        session=db_session,
        embedding_service=embedding,
        bm25_top_k=10,
        vector_top_k=10,
        rrf_k=60,
        result_top_k=30,
    )


def test_retrieve_returns_chunks_scoped_to_vehicle(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    results = svc.retrieve(query="head bolt torque", vehicle_id=v1.id)

    contents = [c.content for c, _ in results]
    # Audi chunks may appear; Ford's "95 Nm" chunk must NOT.
    assert "Cylinder head bolt torque is 95 Nm" not in contents
    assert "Cylinder head bolt torque is 129 Nm" in contents


def test_retrieve_excludes_chunk_ids(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)

    # First call: collect the top result.
    initial = svc.retrieve(query="cylinder head torque", vehicle_id=v1.id)
    excluded_id = initial[0][0].id

    # Second call with that chunk excluded.
    refined = svc.retrieve(
        query="cylinder head torque",
        vehicle_id=v1.id,
        exclude_chunk_ids=frozenset({excluded_id}),
    )
    assert all(c.id != excluded_id for c, _ in refined)


def test_retrieve_returns_empty_when_no_match(db_session):
    """Vehicle with no documents → empty list, no embedding call wasted."""
    v = VehicleRepository(db_session).create(year=2024, make="Tesla", model="Y", engine="electric")
    db_session.flush()
    svc = _make_service(db_session)
    assert svc.retrieve(query="anything", vehicle_id=v.id) == []


def test_retrieve_deduplicates_when_chunk_appears_in_both_retrievers(db_session, vehicle_with_corpus):
    """A chunk that ranks #1 by BM25 *and* #1 by vector must appear once with summed RRF score."""
    v1, _ = vehicle_with_corpus
    # Use an embedding aligned with chunk-1 (which also has 'cylinder head' text).
    svc = _make_service(db_session, query_embedding=[1.0, 0.0, 0.0, 0.0])
    results = svc.retrieve(query="cylinder head", vehicle_id=v1.id)

    ids = [c.id for c, _ in results]
    assert len(ids) == len(set(ids))  # no duplicates

    # The top result should be the chunk that ranks well in both.
    assert "129 Nm" in results[0][0].content


def test_retrieve_orders_by_fused_rrf_score_descending(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    results = svc.retrieve(query="bolt torque", vehicle_id=v1.id)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)
