# app/services/document_service.py
import json
import shutil
from pathlib import Path

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.contextualization_service import ContextualizationService
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import PDFService
from app.utils.paths import get_document_path


class DocumentService:
    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        pdf_service: PDFService,
        chunking_service: StructuredChunkingService,
        contextualization_service: ContextualizationService,
        embedding_service: EmbeddingService,
        docs_dir: str,
    ) -> None:
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._pdf_service = pdf_service
        self._chunking_service = chunking_service
        self._contextualization_service = contextualization_service
        self._embedding_service = embedding_service
        self._docs_dir = docs_dir

    def register_document(
        self, vehicle_id: int, file_name: str, document_type: str = "service_manual"
    ) -> Document:
        doc = self._doc_repo.create(
            vehicle_id=vehicle_id,
            file_name=file_name,
            stored_path="",
            document_type=document_type,
        )
        self._doc_repo.session.flush()  # assigns doc.id
        return doc

    def process_document(self, doc_id: int, pdf_path: str) -> Document:
        doc = self._doc_repo.get_by_id(doc_id)
        if doc is None:
            raise ValueError(f"Document {doc_id} not found")
        source = Path(pdf_path)
        if not source.exists():
            self._doc_repo.update_status(doc.id, "failed")
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        dest = get_document_path(self._docs_dir, doc.vehicle_id, doc.id, doc.file_name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(source, dest)
            doc.stored_path = str(dest)
            page_blocks = self._pdf_service.extract_blocks(str(dest))
            raw_chunks = self._chunking_service.chunk_blocks(page_blocks)
            total = len(raw_chunks)

            if total == 0:
                # No extractable text (scanned / image-only / empty PDF) — flag it instead of
                # silently marking the document "ready" with nothing for the assistant to use.
                self._doc_repo.update_status(doc.id, "no_text")
                return doc

            contexts = [
                self._contextualization_service.generate_context(
                    chunk_content=c["content"],
                    filename=doc.file_name,
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    chunk_index=c["chunk_index"],
                    total_chunks=total,
                )
                for c in raw_chunks
            ]

            contextualized_texts = [
                (
                    f"Document: {doc.file_name} | "
                    f"Section: {c.get('section_title') or 'Unknown'} | "
                    f"Page: {c.get('page_number', 'unknown')}\n"
                    f"{ctx}\n\n{c['content']}"
                )
                for c, ctx in zip(raw_chunks, contexts)
            ]
            embeddings = self._embedding_service.embed_texts(contextualized_texts)

            self._chunk_repo.bulk_create([
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=c["chunk_index"],
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    content=c["content"],
                    context_summary=ctx,
                    embedding_json=json.dumps(emb),
                )
                for c, ctx, emb in zip(raw_chunks, contexts, embeddings)
            ])
            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def add_document(
        self, vehicle_id: int, pdf_path: str, document_type: str = "service_manual"
    ) -> Document:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        doc = self.register_document(vehicle_id, source.name, document_type)
        return self.process_document(doc.id, str(source))

    def list_documents(self, vehicle_id: int) -> list[Document]:
        return self._doc_repo.list_by_vehicle(vehicle_id)
