from unittest.mock import MagicMock

import fitz  # PyMuPDF

from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.models.vehicle import Vehicle
from app.services.contextualization_service import ContextualizationService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Valve clearance intake is 0.20 mm cold.")
    doc.save(str(path))
    doc.close()


def _service(session, docs_dir):
    emb = MagicMock(spec=EmbeddingService)
    emb.embed_texts.side_effect = lambda texts: [[0.0, 1.0] for _ in texts]
    ctx = MagicMock(spec=ContextualizationService)
    ctx.generate_context.side_effect = lambda **kwargs: "context summary"
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(500, 100),
        contextualization_service=ctx,
        embedding_service=emb,
        docs_dir=str(docs_dir),
    )


def test_register_creates_pending_row(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")

    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")

    assert doc.id is not None
    assert doc.processing_status == "pending"


def test_process_marks_ready_and_stores_chunks(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")
    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")
    pdf = tmp_path / "m.pdf"
    _make_pdf(pdf)

    result = svc.process_document(doc.id, str(pdf))

    assert result.processing_status == "ready"
    chunks = ChunkRepository(db_session).list_by_vehicle(1)
    assert len(chunks) >= 1


def test_process_marks_failed_on_missing_file(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")
    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")

    try:
        svc.process_document(doc.id, str(tmp_path / "does-not-exist.pdf"))
    except FileNotFoundError:
        pass

    assert DocumentRepository(db_session).get_by_id(doc.id).processing_status == "failed"
