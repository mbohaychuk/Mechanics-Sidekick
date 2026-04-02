# app/services/document_service.py
import json
import shutil
from pathlib import Path

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import PDFService
from app.utils.paths import get_document_path


class DocumentService:
    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        pdf_service: PDFService,
        chunking_service: ChunkingService,
        embedding_service: EmbeddingService,
        docs_dir: str,
    ) -> None:
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._pdf_service = pdf_service
        self._chunking_service = chunking_service
        self._embedding_service = embedding_service
        self._docs_dir = docs_dir

    def add_document(self, vehicle_id: int, pdf_path: str, document_type: str = "service_manual") -> Document:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = self._doc_repo.create(
            vehicle_id=vehicle_id,
            file_name=source.name,
            stored_path="",
            document_type=document_type,
        )
        self._doc_repo.session.flush()  # assigns doc.id

        dest = get_document_path(self._docs_dir, vehicle_id, doc.id, source.name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(source, dest)
            doc.stored_path = str(dest)
            pages = self._pdf_service.extract_pages(str(dest))
            raw_chunks = self._chunking_service.chunk_pages(pages)
            texts = [c["content"] for c in raw_chunks]
            embeddings = self._embedding_service.embed_texts(texts)

            self._chunk_repo.bulk_create([
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=c["chunk_index"],
                    page_number=c.get("page_number"),
                    content=c["content"],
                    embedding_json=json.dumps(emb),
                )
                for c, emb in zip(raw_chunks, embeddings)
            ])
            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def list_documents(self, vehicle_id: int) -> list[Document]:
        return self._doc_repo.list_by_vehicle(vehicle_id)
