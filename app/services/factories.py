from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import OpenAIProvider
from app.config import Settings
from app.repositories.chat_repository import ChatRepository
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.document_service import DocumentService
from app.services.llm_factory import (
    make_contextualization_service,
    make_embedding_service,
)
from app.services.pdf_service import PDFService
from app.services.retrieval_service import RetrievalService
from app.services.structured_chunking_service import StructuredChunkingService


def make_document_service(session: Session, settings: Settings) -> DocumentService:
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


def make_chat_orchestrator(session: Session, settings: Settings) -> AgentOrchestrator:
    retrieval = RetrievalService(
        ChunkRepository(session),
        make_embedding_service(settings),
        settings.top_k_chunks,
    )
    provider = OpenAIProvider(
        api_key=settings.openai_api_key or None,
        model=settings.openai_chat_model,
    )
    return AgentOrchestrator(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=settings.recent_messages,
        max_iters=settings.max_agent_iters,
    )
