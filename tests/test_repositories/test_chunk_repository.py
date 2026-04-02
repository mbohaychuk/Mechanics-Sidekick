# tests/test_repositories/test_chunk_repository.py
import json
import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository
from app.models.document_chunk import DocumentChunk


@pytest.fixture
def vehicle_and_ready_doc(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    doc = DocumentRepository(db_session).create(vehicle.id, "manual.pdf", "/tmp/manual.pdf")
    doc.processing_status = "ready"
    db_session.flush()
    return vehicle, doc


def test_bulk_create_and_list_by_vehicle(db_session, vehicle_and_ready_doc):
    vehicle, doc = vehicle_and_ready_doc
    chunk_repo = ChunkRepository(db_session)
    chunk_repo.bulk_create([
        DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1,
                      content="Torque spec is 129 Nm", embedding_json=json.dumps([0.1, 0.2])),
        DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2,
                      content="Rotor thickness 20mm", embedding_json=json.dumps([0.3, 0.4])),
    ])
    db_session.flush()

    results = chunk_repo.list_by_vehicle(vehicle.id)
    assert len(results) == 2
    assert results[0].content == "Torque spec is 129 Nm"


def test_list_by_vehicle_excludes_pending_docs(db_session):
    vehicle = VehicleRepository(db_session).create(year=2019, make="GM", model="Sierra", engine="5.3L")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    ready_doc = doc_repo.create(vehicle.id, "ready.pdf", "/tmp/ready.pdf")
    ready_doc.processing_status = "ready"
    pending_doc = doc_repo.create(vehicle.id, "pending.pdf", "/tmp/pending.pdf")
    # pending_doc stays "pending"
    db_session.flush()

    chunk_repo = ChunkRepository(db_session)
    chunk_repo.bulk_create([
        DocumentChunk(document_id=ready_doc.id, chunk_index=0, page_number=1,
                      content="Ready content", embedding_json="[0.1]"),
        DocumentChunk(document_id=pending_doc.id, chunk_index=0, page_number=1,
                      content="Pending content", embedding_json="[0.2]"),
    ])
    db_session.flush()

    results = chunk_repo.list_by_vehicle(vehicle.id)
    assert len(results) == 1
    assert results[0].content == "Ready content"
