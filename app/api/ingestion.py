from pathlib import Path

from app.config import Settings
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.llm_factory import (
    make_contextualization_service,
    make_embedding_service,
)
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService


def build_document_service(session, settings: Settings) -> DocumentService:
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(
            settings.chunk_size, settings.chunk_overlap
        ),
        contextualization_service=make_contextualization_service(settings),
        embedding_service=make_embedding_service(settings),
        docs_dir=settings.docs_dir,
    )


def _mark_failed(session_factory, doc_id: int) -> None:
    session = session_factory()
    try:
        DocumentRepository(session).update_status(doc_id, "failed")
        session.commit()
    finally:
        session.close()


def ingest_document(session_factory, settings: Settings, doc_id: int, pdf_path: str) -> None:
    session = session_factory()
    try:
        build_document_service(session, settings).process_document(doc_id, pdf_path)
        session.commit()
    except Exception:
        session.rollback()
        _mark_failed(session_factory, doc_id)
    finally:
        session.close()
        Path(pdf_path).unlink(missing_ok=True)
