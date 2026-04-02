# tests/test_repositories/test_chat_repository.py
import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.job_repository import JobRepository
from app.repositories.chat_repository import ChatRepository


@pytest.fixture
def job(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    j = JobRepository(db_session).create(vehicle_id=vehicle.id, title="Brake Job")
    db_session.flush()
    return j


def test_create_message(db_session, job):
    repo = ChatRepository(db_session)
    msg = repo.create(job_id=job.id, role="user", content="What is the torque spec?")
    db_session.flush()
    assert msg.id is not None
    assert msg.role == "user"
    assert msg.sources_json is None


def test_list_by_job_ordered_ascending(db_session, job):
    repo = ChatRepository(db_session)
    repo.create(job_id=job.id, role="user", content="First")
    repo.create(job_id=job.id, role="assistant", content="Answer")
    repo.create(job_id=job.id, role="user", content="Second")
    db_session.flush()

    messages = repo.list_by_job(job.id)
    assert len(messages) == 3
    assert messages[0].content == "First"
    assert messages[2].content == "Second"


def test_list_by_job_with_limit_returns_most_recent(db_session, job):
    repo = ChatRepository(db_session)
    for i in range(10):
        repo.create(job_id=job.id, role="user", content=f"msg {i}")
    db_session.flush()

    messages = repo.list_by_job(job.id, limit=4)
    assert len(messages) == 4
    assert messages[0].content == "msg 6"
    assert messages[3].content == "msg 9"
