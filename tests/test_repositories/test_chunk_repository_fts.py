import json

from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.vehicle_repository import VehicleRepository


def _vehicle(db_session, make):
    v = VehicleRepository(db_session).create(year=2015, make=make, model="F-150", engine="5.0L")
    db_session.flush()
    return v


def _doc(db_session, vehicle_id, status="ready"):
    doc = DocumentRepository(db_session).create(vehicle_id=vehicle_id, file_name="m.pdf", stored_path="/tmp/m.pdf")
    doc.processing_status = status
    db_session.flush()
    return doc


def _chunk(doc_id, idx, content):
    return DocumentChunk(document_id=doc_id, chunk_index=idx, page_number=idx + 1,
                         content=content, section_title="S", embedding_json=json.dumps([1.0]))


def test_search_fts_matches_and_is_scoped_to_vehicle(db_session):
    v1, v2 = _vehicle(db_session, "Ford"), _vehicle(db_session, "GM")
    repo = ChunkRepository(db_session)
    d1, d2 = _doc(db_session, v1.id), _doc(db_session, v2.id)
    repo.bulk_create([
        _chunk(d1.id, 0, "DTC P0420 catalyst efficiency below threshold"),
        _chunk(d1.id, 1, "minimum rotor thickness specification"),
        _chunk(d2.id, 0, "P0420 noted on the Sierra"),
    ])
    db_session.flush()

    ids = repo.search_fts(v1.id, "What does P0420 mean?", limit=10)

    v1_hit = db_session.query(DocumentChunk).filter_by(document_id=d1.id, chunk_index=0).one()
    v2_hit = db_session.query(DocumentChunk).filter_by(document_id=d2.id, chunk_index=0).one()
    assert v1_hit.id in ids        # the matching chunk for THIS vehicle
    assert v2_hit.id not in ids    # cross-vehicle isolation (must-fix)


def test_search_fts_excludes_non_ready_documents(db_session):
    v = _vehicle(db_session, "Ford")
    repo = ChunkRepository(db_session)
    doc = _doc(db_session, v.id, status="processing")  # FTS rows exist before 'ready'
    repo.bulk_create([_chunk(doc.id, 0, "P0420 catalyst")])
    db_session.flush()

    assert repo.search_fts(v.id, "P0420", limit=10) == []  # half-ingested must not leak (must-fix)


def test_delete_by_document_clears_fts_index(db_session):
    v = _vehicle(db_session, "Ford")
    repo = ChunkRepository(db_session)
    doc = _doc(db_session, v.id)
    repo.bulk_create([_chunk(doc.id, 0, "P0420 catalyst")])
    db_session.flush()
    assert repo.search_fts(v.id, "P0420", limit=10)  # present

    repo.delete_by_document(doc.id)
    db_session.flush()

    assert repo.search_fts(v.id, "P0420", limit=10) == []  # contentful FTS row removed, no orphan
