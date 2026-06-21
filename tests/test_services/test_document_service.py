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
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.contextualization_service import ContextualizationService
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


def _make_svc(db_session, docs_dir, mock_embedding, mock_contextualization=None, chunks=None, **kwargs):
    if mock_contextualization is None:
        mock_contextualization = MagicMock(spec=ContextualizationService)
        mock_contextualization.generate_context.return_value = "Test context summary."

    mock_chunking = MagicMock(spec=StructuredChunkingService)
    mock_chunking.chunk_blocks.return_value = chunks if chunks is not None else [
        {"chunk_index": 0, "page_number": 1, "section_title": "TEST SECTION", "content": "Torque spec is 129 Nm"}
    ]

    return DocumentService(
        doc_repo=DocumentRepository(db_session),
        chunk_repo=ChunkRepository(db_session),
        pdf_service=PDFService(),
        chunking_service=mock_chunking,
        contextualization_service=mock_contextualization,
        embedding_service=mock_embedding,
        docs_dir=docs_dir,
        **kwargs,
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


def test_large_doc_skips_contextualization_batches_embeddings_and_tracks_progress(
    db_session, vehicle, sample_pdf, tmp_path
):
    # 5 chunks, batch size 2, contextualize cap 3 -> skip per-chunk LLM context, embed in 3 batches.
    chunks = [
        {"chunk_index": i, "page_number": i + 1, "section_title": "S", "content": f"chunk {i}"}
        for i in range(5)
    ]
    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.embed_texts.side_effect = lambda texts: [[0.1, 0.2] for _ in texts]
    mock_ctx = MagicMock(spec=ContextualizationService)

    svc = _make_svc(db_session, str(tmp_path / "docs"), mock_embedding, mock_ctx,
                    chunks=chunks, embed_batch_size=2, contextualize_max_chunks=3)

    doc = svc.add_document(vehicle_id=vehicle.id, pdf_path=str(sample_pdf))
    db_session.flush()

    assert doc.processing_status == "ready"
    assert doc.chunks_total == 5 and doc.chunks_done == 5
    mock_ctx.generate_context.assert_not_called()           # skipped above the cap
    assert mock_embedding.embed_texts.call_count == 3        # ceil(5/2) batches
    assert len(ChunkRepository(db_session).list_by_vehicle(vehicle.id)) == 5


def test_add_document_with_no_extractable_text_is_marked_no_text(db_session, vehicle, sample_pdf, tmp_path):
    # A scanned / image-only PDF yields zero chunks; it must NOT be marked "ready" silently.
    mock_embedding = MagicMock(spec=EmbeddingService)
    svc = _make_svc(db_session, str(tmp_path / "docs"), mock_embedding)
    svc._chunking_service.chunk_blocks.return_value = []

    doc = svc.add_document(vehicle_id=vehicle.id, pdf_path=str(sample_pdf))
    db_session.flush()

    assert doc.processing_status == "no_text"
    mock_embedding.embed_texts.assert_not_called()
    assert ChunkRepository(db_session).list_by_vehicle(vehicle.id) == []


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
