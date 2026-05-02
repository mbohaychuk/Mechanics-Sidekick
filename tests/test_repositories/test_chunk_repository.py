# tests/test_repositories/test_chunk_repository.py
import pytest
from sqlalchemy import text
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.models.document_chunk import DocumentChunk


@pytest.fixture
def vehicle_and_ready_doc(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    doc = DocumentRepository(db_session).create(vehicle.id, "manual.pdf", "/tmp/manual.pdf")
    doc.processing_status = "ready"
    db_session.flush()
    return vehicle, doc


def test_bulk_create_writes_to_chunks_fts_and_vec(db_session, vehicle_and_ready_doc):
    _, doc = vehicle_and_ready_doc
    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, content="Torque spec is 129 Nm"),
            indexable_text="Torque spec is 129 Nm for the brake caliper",
            embedding=[0.1, 0.2, 0.3, 0.4],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2, content="Rotor thickness 20mm"),
            indexable_text="Minimum rotor thickness 20mm front discs",
            embedding=[0.5, 0.6, 0.7, 0.8],
        ),
    ])
    db_session.flush()

    fts_count = db_session.execute(text("SELECT COUNT(*) FROM document_chunks_fts")).scalar()
    vec_count = db_session.execute(text("SELECT COUNT(*) FROM document_chunks_vec")).scalar()
    assert fts_count == 2
    assert vec_count == 2

    # FTS5 chunk_id column matches document_chunks.id
    fts_ids = {row[0] for row in db_session.execute(text("SELECT chunk_id FROM document_chunks_fts")).fetchall()}
    main_ids = {row[0] for row in db_session.execute(text("SELECT id FROM document_chunks")).fetchall()}
    assert fts_ids == main_ids


def test_list_by_vehicle_returns_chunks_in_order(db_session, vehicle_and_ready_doc):
    vehicle, doc = vehicle_and_ready_doc
    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, content="first"),
            indexable_text="first",
            embedding=[1.0, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2, content="second"),
            indexable_text="second",
            embedding=[0.0, 1.0, 0.0, 0.0],
        ),
    ])
    db_session.flush()

    rows = repo.list_by_vehicle(vehicle.id)
    assert len(rows) == 2
    assert rows[0].content == "first"
    assert rows[1].content == "second"


def test_list_by_vehicle_excludes_pending_docs(db_session):
    vehicle = VehicleRepository(db_session).create(year=2019, make="GM", model="Sierra", engine="5.3L")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    ready_doc = doc_repo.create(vehicle.id, "ready.pdf", "/tmp/ready.pdf")
    ready_doc.processing_status = "ready"
    pending_doc = doc_repo.create(vehicle.id, "pending.pdf", "/tmp/pending.pdf")
    db_session.flush()

    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=ready_doc.id, chunk_index=0, page_number=1, content="Ready content"),
            indexable_text="Ready content",
            embedding=[0.1, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=pending_doc.id, chunk_index=0, page_number=1, content="Pending content"),
            indexable_text="Pending content",
            embedding=[0.0, 0.1, 0.0, 0.0],
        ),
    ])
    db_session.flush()

    rows = repo.list_by_vehicle(vehicle.id)
    assert len(rows) == 1
    assert rows[0].content == "Ready content"
