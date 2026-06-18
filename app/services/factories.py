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


def make_document_service(session, settings: Settings) -> DocumentService:
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
