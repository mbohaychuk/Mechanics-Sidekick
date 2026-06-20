from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import OpenAIProvider
from app.config import Settings
from app.diagnostic.commentary import CommentaryGenerator
from app.diagnostic.diagnosis import Diagnoser
from app.diagnostic.protocol import get_protocol
from app.diagnostic.report import ReportBuilder
from app.diagnostic.session import DiagnosticSessionRunner
from app.models.vehicle import Vehicle
from app.repositories.chat_repository import ChatRepository
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository
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


def make_chat_orchestrator(
    session: Session, settings: Settings, obd_host=None
) -> AgentOrchestrator:
    retrieval = RetrievalService(
        ChunkRepository(session),
        make_embedding_service(settings),
        settings.top_k_chunks,
    )
    provider = OpenAIProvider(
        api_key=settings.openai_api_key or None,
        model=settings.openai_chat_model,
    )
    web_search_client = None
    if settings.web_search_enabled and settings.tavily_api_key:
        from tavily import TavilyClient

        web_search_client = TavilyClient(api_key=settings.tavily_api_key)
    return AgentOrchestrator(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=settings.recent_messages,
        max_iters=settings.max_agent_iters,
        obd_host=obd_host,
        web_search_client=web_search_client,
        web_search_max_results=settings.web_search_max_results,
        diag_repo=DiagnosticSessionRepository(session),
    )


def make_diagnostic_runner(session_factory, settings: Settings, manager, host, vehicle_id: int, protocol_name: str) -> DiagnosticSessionRunner | None:
    if manager is None or host is None or not host.available:
        return None

    s = session_factory()
    try:
        vehicle = s.get(Vehicle, vehicle_id)
        if vehicle is None:
            return None
        vehicle_label = f"{vehicle.year} {vehicle.make} {vehicle.model}, engine {vehicle.engine}"
    finally:
        s.close()

    provider = OpenAIProvider(api_key=settings.openai_api_key or None, model=settings.openai_chat_model)
    web_client = None
    if settings.web_search_enabled and settings.tavily_api_key:
        from tavily import TavilyClient
        web_client = TavilyClient(api_key=settings.tavily_api_key)

    embedding = make_embedding_service(settings)

    def diagnoser_factory(session):
        retrieval = RetrievalService(ChunkRepository(session), embedding, settings.top_k_chunks)
        return Diagnoser(retrieval, DocumentRepository(session), web_client, vehicle_id, settings)

    return DiagnosticSessionRunner(
        manager=manager,
        session_factory=session_factory,
        vehicle_id=vehicle_id,
        vehicle_label=vehicle_label,
        protocol=get_protocol(protocol_name),
        commentary=CommentaryGenerator(provider, settings),
        diagnoser_factory=diagnoser_factory,
        report_builder=ReportBuilder(provider, settings),
        settings=settings,
    )
