import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository


@pytest.fixture
def vehicle(db_session):
    v = VehicleRepository(db_session).create(year=2020, make="Toyota", model="Tacoma", engine="3.5L")
    db_session.flush()
    return v


def test_create_and_get_by_id(db_session, vehicle):
    repo = DocumentRepository(db_session)
    doc = repo.create(vehicle.id, "manual.pdf", "/docs/manual.pdf")
    db_session.flush()

    fetched = repo.get_by_id(doc.id)
    assert fetched is not None
    assert fetched.file_name == "manual.pdf"
    assert fetched.processing_status == "pending"


def test_get_by_id_returns_none_when_missing(db_session):
    assert DocumentRepository(db_session).get_by_id(9999) is None


def test_list_by_vehicle_returns_all_statuses(db_session, vehicle):
    repo = DocumentRepository(db_session)
    repo.create(vehicle.id, "a.pdf", "/docs/a.pdf")
    repo.create(vehicle.id, "b.pdf", "/docs/b.pdf")
    db_session.flush()

    docs = repo.list_by_vehicle(vehicle.id)
    assert len(docs) == 2


def test_update_status_changes_processing_status(db_session, vehicle):
    repo = DocumentRepository(db_session)
    doc = repo.create(vehicle.id, "manual.pdf", "/docs/manual.pdf")
    db_session.flush()

    repo.update_status(doc.id, "ready")
    assert doc.processing_status == "ready"


def test_update_status_raises_when_missing(db_session):
    with pytest.raises(ValueError, match="Document 9999 not found"):
        DocumentRepository(db_session).update_status(9999, "ready")
