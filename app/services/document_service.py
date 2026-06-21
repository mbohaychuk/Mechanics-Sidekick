# app/services/document_service.py
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
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

logger = logging.getLogger(__name__)


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
        embed_batch_size: int = 128,
        ingest_concurrency: int = 8,
        contextualize_max_chunks: int = 1500,
    ) -> None:
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._pdf_service = pdf_service
        self._chunking_service = chunking_service
        self._contextualization_service = contextualization_service
        self._embedding_service = embedding_service
        self._docs_dir = docs_dir
        self._embed_batch_size = max(1, embed_batch_size)
        self._ingest_concurrency = max(1, ingest_concurrency)
        self._contextualize_max_chunks = contextualize_max_chunks

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

            # Per-chunk LLM context is one call per chunk; for very large manuals that's thousands
            # of calls, so above a threshold we skip it and embed the raw chunk + its metadata header
            # (filename / section / page) — still situated, just without the LLM summary.
            contextualize = total <= self._contextualize_max_chunks

            doc.chunks_total = total
            doc.chunks_done = 0
            self._doc_repo.session.commit()

            done = 0
            with ThreadPoolExecutor(max_workers=self._ingest_concurrency) as pool:
                for start in range(0, total, self._embed_batch_size):
                    batch = raw_chunks[start:start + self._embed_batch_size]
                    if contextualize:
                        contexts = list(pool.map(
                            lambda c: self._safe_context(c, doc.file_name, total), batch
                        ))
                    else:
                        contexts = ["" for _ in batch]

                    enriched = [self._enriched_text(doc.file_name, c, ctx) for c, ctx in zip(batch, contexts)]
                    embeddings = self._embedding_service.embed_texts(enriched)

                    self._chunk_repo.bulk_create([
                        DocumentChunk(
                            document_id=doc.id,
                            chunk_index=c["chunk_index"],
                            page_number=c.get("page_number"),
                            section_title=c.get("section_title"),
                            content=c["content"],
                            context_summary=ctx or None,
                            embedding_json=json.dumps(emb),
                        )
                        for c, ctx, emb in zip(batch, contexts, embeddings)
                    ])
                    done += len(batch)
                    doc.chunks_done = done
                    self._doc_repo.session.commit()  # surface progress to the polling UI

            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.session.rollback()
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def _safe_context(self, chunk: dict, filename: str, total: int) -> str:
        """Generate a chunk's context summary; degrade to '' on failure rather than failing the doc."""
        try:
            return self._contextualization_service.generate_context(
                chunk_content=chunk["content"],
                filename=filename,
                page_number=chunk.get("page_number"),
                section_title=chunk.get("section_title"),
                chunk_index=chunk["chunk_index"],
                total_chunks=total,
            )
        except Exception:
            logger.exception("context generation failed for chunk %s", chunk.get("chunk_index"))
            return ""

    @staticmethod
    def _enriched_text(filename: str, chunk: dict, context: str) -> str:
        header = (
            f"Document: {filename} | "
            f"Section: {chunk.get('section_title') or 'Unknown'} | "
            f"Page: {chunk.get('page_number', 'unknown')}"
        )
        body = f"{context}\n\n{chunk['content']}" if context else chunk["content"]
        return f"{header}\n{body}"

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
