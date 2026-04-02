# app/services/chat_service.py
import json

from app.rag.prompt_builder import build_messages
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.ollama_service import OllamaService
from app.services.retrieval_service import RetrievalService


class ChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        job_repo: JobRepository,
        vehicle_repo: VehicleRepository,
        doc_repo: DocumentRepository,
        retrieval_service: RetrievalService,
        ollama_service: OllamaService,
        chat_model: str,
        recent_messages_limit: int = 6,
    ) -> None:
        self._chat_repo = chat_repo
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo
        self._doc_repo = doc_repo
        self._retrieval = retrieval_service
        self._ollama = ollama_service
        self._chat_model = chat_model
        self._recent_messages_limit = recent_messages_limit

    def ask(self, job_id: int, question: str) -> tuple[str, list[dict]]:
        job = self._job_repo.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        vehicle = self._vehicle_repo.get_by_id(job.vehicle_id)
        if vehicle is None:
            raise ValueError(f"Vehicle {job.vehicle_id} not found for job {job_id}")

        # Capture history before saving the current user message
        recent = self._chat_repo.list_by_job(job_id, limit=self._recent_messages_limit)
        self._chat_repo.create(job_id=job_id, role="user", content=question)

        chunks = self._retrieval.retrieve(vehicle_id=job.vehicle_id, question=question)

        if not chunks:
            no_context = "I could not find any relevant information in the available manuals."
            self._chat_repo.create(job_id=job_id, role="assistant", content=no_context, sources_json="[]")
            return no_context, []

        doc_ids = list({chunk.document_id for chunk, _ in chunks})
        document_map: dict[int, str] = {}
        for doc_id in doc_ids:
            doc = self._doc_repo.get_by_id(doc_id)
            if doc:
                document_map[doc_id] = doc.file_name

        messages = build_messages(job, vehicle, recent, chunks, question, document_map)
        answer = self._ollama.chat(messages, self._chat_model)

        sources = [
            {
                "filename": document_map.get(chunk.document_id, f"document_{chunk.document_id}"),
                "page": chunk.page_number,
                "score": round(score, 4),
            }
            for chunk, score in chunks
        ]

        self._chat_repo.create(
            job_id=job_id,
            role="assistant",
            content=answer,
            sources_json=json.dumps(sources),
        )

        return answer, sources
