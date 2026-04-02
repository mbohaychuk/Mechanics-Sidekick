# tests/test_services/test_document_service.py
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock

import fitz

from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository
from app.services.vehicle_service import VehicleService
from app.services.document_service import DocumentService
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService


@pytest.fixture
def vehicle(db_session):
    svc = VehicleService(VehicleRepository(db_session))
    v = svc.add_vehicle(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    return v


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    path = tmp_path / "manual.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Torque spec is 129 Nm for caliper bracket bolts")
    doc.save(str(path))
    doc.close()
    return path


def _make_svc(db_session, docs_dir, mock_embedding):
    return DocumentService(
        doc_repo=DocumentRepository(db_session),
        chunk_repo=ChunkRepository(db_session),
        pdf_service=PDFService(),
        chunking_service=ChunkingService(chunk_size=50, chunk_overlap=5),
        embedding_service=mock_embedding,
        docs_dir=docs_dir,
    )


def test_add_document_creates_record_copies_file_and_stores_chunks(db_session, vehicle, sample_pdf, tmp_path):
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_texts.return_value = [[0.1, 0.2, 0.3]]

    docs_dir = str(tmp_path / "docs")
    svc = _make_svc(db_session, docs_dir, mock_embedding)

    doc = svc.add_document(vehicle_id=vehicle.id, pdf_path=str(sample_pdf))
    db_session.flush()

    assert doc.id is not None
    assert doc.vehicle_id == vehicle.id
    assert doc.processing_status == "ready"
    assert Path(doc.stored_path).exists()

    chunks = ChunkRepository(db_session).list_by_vehicle(vehicle.id)
    assert len(chunks) >= 1
    assert json.loads(chunks[0].embedding_json) == [0.1, 0.2, 0.3]


def test_add_document_raises_when_file_missing(db_session, vehicle, tmp_path):
    mock_embedding = MagicMock(spec=EmbeddingService)
    svc = _make_svc(db_session, str(tmp_path / "docs"), mock_embedding)
    with pytest.raises(FileNotFoundError):
        svc.add_document(vehicle_id=vehicle.id, pdf_path="/nonexistent/path.pdf")


def test_add_document_marks_failed_on_embedding_error(db_session, vehicle, sample_pdf, tmp_path):
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_texts.side_effect = RuntimeError("Ollama unreachable")

    svc = _make_svc(db_session, str(tmp_path / "docs"), mock_embedding)
    with pytest.raises(RuntimeError, match="Document processing failed"):
        svc.add_document(vehicle_id=vehicle.id, pdf_path=str(sample_pdf))

    docs = DocumentRepository(db_session).list_by_vehicle(vehicle.id)
    assert len(docs) == 1
    assert docs[0].processing_status == "failed"
