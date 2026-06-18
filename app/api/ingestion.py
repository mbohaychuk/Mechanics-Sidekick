import logging
from pathlib import Path

from app.config import Settings
from app.repositories.document_repository import DocumentRepository
from app.services.factories import make_document_service

logger = logging.getLogger(__name__)


def _mark_failed(session_factory, doc_id: int) -> None:
    session = session_factory()
    try:
        DocumentRepository(session).update_status(doc_id, "failed")
        session.commit()
    except Exception:
        logger.exception("failed to mark document %s failed", doc_id)
    finally:
        session.close()


def ingest_document(session_factory, settings: Settings, doc_id: int, pdf_path: str) -> None:
    session = session_factory()
    try:
        make_document_service(session, settings).process_document(doc_id, pdf_path)
        session.commit()
    except Exception:
        logger.exception("ingestion failed for document %s", doc_id)
        session.rollback()
        _mark_failed(session_factory, doc_id)
    finally:
        session.close()
        Path(pdf_path).unlink(missing_ok=True)
