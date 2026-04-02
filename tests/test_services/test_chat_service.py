# tests/test_services/test_chat_service.py
import json
import pytest
from unittest.mock import MagicMock

from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.chat_repository import ChatRepository
from app.services.retrieval_service import RetrievalService
from app.services.ollama_service import OllamaService
from app.services.chat_service import ChatService


@pytest.fixture
def job_and_vehicle(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    job = JobRepository(db_session).create(vehicle_id=vehicle.id, title="Brake Job")
    db_session.flush()
    return job, vehicle


def _make_svc(db_session, mock_retrieval, mock_ollama, mock_doc_repo=None):
    return ChatService(
        chat_repo=ChatRepository(db_session),
        job_repo=JobRepository(db_session),
        vehicle_repo=VehicleRepository(db_session),
        doc_repo=mock_doc_repo or DocumentRepository(db_session),
        retrieval_service=mock_retrieval,
        ollama_service=mock_ollama,
        chat_model="test-model",
        recent_messages_limit=6,
    )


def test_ask_saves_user_and_assistant_messages_and_returns_sources(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle

    mock_chunk = MagicMock()
    mock_chunk.document_id = 99
    mock_chunk.page_number = 214
    mock_chunk.content = "Torque spec is 129 Nm"
    mock_chunk.embedding_json = json.dumps([0.1])

    mock_retrieval = MagicMock(spec=RetrievalService)
    mock_retrieval.retrieve.return_value = [(mock_chunk, 0.95)]

    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.chat.return_value = "The torque spec is 129 Nm."

    mock_doc = MagicMock()
    mock_doc.file_name = "brake_manual.pdf"
    mock_doc_repo = MagicMock()
    mock_doc_repo.get_by_id.return_value = mock_doc

    svc = _make_svc(db_session, mock_retrieval, mock_ollama, mock_doc_repo)
    answer, sources = svc.ask(job_id=job.id, question="What is the torque spec?")
    db_session.flush()

    assert "129 Nm" in answer
    assert len(sources) == 1
    assert sources[0]["filename"] == "brake_manual.pdf"
    assert sources[0]["page"] == 214

    messages = ChatRepository(db_session).list_by_job(job.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].sources_json is not None


def test_ask_returns_no_context_message_when_no_chunks(db_session, job_and_vehicle):
    job, _ = job_and_vehicle

    mock_retrieval = MagicMock(spec=RetrievalService)
    mock_retrieval.retrieve.return_value = []
    mock_ollama = MagicMock(spec=OllamaService)

    svc = _make_svc(db_session, mock_retrieval, mock_ollama)
    answer, sources = svc.ask(job_id=job.id, question="Anything?")

    assert sources == []
    assert "not find" in answer.lower() or "no" in answer.lower()
    mock_ollama.chat.assert_not_called()

    db_session.flush()
    messages = ChatRepository(db_session).list_by_job(job.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


def test_ask_raises_when_job_not_found(db_session):
    mock_retrieval = MagicMock(spec=RetrievalService)
    mock_ollama = MagicMock(spec=OllamaService)
    svc = _make_svc(db_session, mock_retrieval, mock_ollama)
    with pytest.raises(ValueError, match="Job 999 not found"):
        svc.ask(job_id=999, question="Any question")
