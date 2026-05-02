# app/services/document_service.py
import re
import shutil
from pathlib import Path

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repository import ChunkInsert, ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService
from app.services.metadata_extractor import MetadataExtractor
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.table_chunker import TableChunker
from app.utils.paths import get_document_path


class DocumentService:
    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        pdf_service: PDFService,
        chunking_service: StructuredChunkingService,
        table_chunker: TableChunker,
        contextualization_service: ContextualizationService,
        embedding_service: EmbeddingService,
        metadata_extractor: MetadataExtractor,
        docs_dir: str,
    ) -> None:
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._pdf_service = pdf_service
        self._chunking_service = chunking_service
        self._table_chunker = table_chunker
        self._contextualization_service = contextualization_service
        self._embedding_service = embedding_service
        self._metadata_extractor = metadata_extractor
        self._docs_dir = docs_dir

    def add_document(
        self,
        vehicle_id: int,
        pdf_path: str,
        document_type: str = "service_manual",
    ) -> Document:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = self._doc_repo.create(
            vehicle_id=vehicle_id,
            file_name=source.name,
            stored_path="",
            document_type=document_type,
        )
        self._doc_repo.session.flush()

        dest = get_document_path(self._docs_dir, vehicle_id, doc.id, source.name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(source, dest)
            doc.stored_path = str(dest)

            # 1. Extract blocks + tables.
            page_blocks = self._pdf_service.extract_blocks(str(dest))
            table_pages = self._pdf_service.extract_tables(str(dest))

            # 2. Section title map for table chunks (best-effort: use the
            # section detected per-page by the structured chunker on its
            # first pass over the page so table chunks share section titles
            # with surrounding prose). Compute by running the prose chunker
            # without exclusions — cheap, doesn't reach the embedder.
            section_titles_by_page = self._extract_section_titles(page_blocks)
            exclude_bboxes = self._table_chunker.bboxes_by_page(table_pages)

            # 3. Build raw chunks: tables first (claim chunk indices 0..N), prose after.
            table_chunks = self._table_chunker.chunk_tables(
                table_pages,
                base_chunk_index=0,
                section_titles_by_page=section_titles_by_page,
            )
            base_idx_for_prose = (
                max((c["chunk_index"] for c in table_chunks), default=-1) + 1
            )
            prose_chunks_raw = self._chunking_service.chunk_blocks(
                page_blocks, exclude_bboxes_per_page=exclude_bboxes
            )
            prose_chunks = [
                {**c, "chunk_index": base_idx_for_prose + i, "chunk_kind": "prose",
                 "table_id": None, "table_type": None}
                for i, c in enumerate(prose_chunks_raw)
            ]
            raw_chunks = table_chunks + prose_chunks

            # 4. Engine variant — once per document.
            sample_text = "\n".join(c["content"] for c in raw_chunks[:5])
            engine_variant = self._metadata_extractor.extract_engine_variant(
                filename=source.name, sample_text=sample_text,
            )

            # 5. Table type — per chunk for table_* kinds.
            for c in raw_chunks:
                if c["chunk_kind"] in ("table_row", "table_whole"):
                    header = self._extract_header(c["content"])
                    c["table_type"] = self._metadata_extractor.classify_table_type(
                        section_title=c.get("section_title"), header=header,
                    )

            # 6. Contextualize.
            total = len(raw_chunks)
            contexts = [
                self._contextualization_service.generate_context(
                    chunk_content=c["content"],
                    filename=source.name,
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    chunk_index=c["chunk_index"],
                    total_chunks=total,
                )
                for c in raw_chunks
            ]

            # 7. Build embedding inputs (also the FTS5-indexed text).
            indexable_texts = [
                (
                    f"Document: {source.name} | "
                    f"Section: {c.get('section_title') or 'Unknown'} | "
                    f"Page: {c.get('page_number', 'unknown')}\n"
                    f"{ctx}\n\n{c['content']}"
                )
                for c, ctx in zip(raw_chunks, contexts)
            ]
            embeddings = self._embedding_service.embed_texts(indexable_texts)

            # 8. Persist to all three tables.
            self._chunk_repo.bulk_create([
                ChunkInsert(
                    chunk=DocumentChunk(
                        document_id=doc.id,
                        chunk_index=c["chunk_index"],
                        page_number=c.get("page_number"),
                        section_title=c.get("section_title"),
                        content=c["content"],
                        context_summary=ctx,
                        chunk_kind=c["chunk_kind"],
                        engine_variant=engine_variant,
                        table_type=c.get("table_type"),
                        table_id=c.get("table_id"),
                    ),
                    indexable_text=text,
                    embedding=emb,
                )
                for c, ctx, text, emb in zip(raw_chunks, contexts, indexable_texts, embeddings)
            ])

            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def list_documents(self, vehicle_id: int) -> list[Document]:
        return self._doc_repo.list_by_vehicle(vehicle_id)

    # --- Private helpers -----------------------------------------------------

    def _extract_section_titles(self, page_blocks: list[dict]) -> dict[int, str]:
        """Best-effort: nearest preceding section heading per page."""
        titles_by_page: dict[int, str] = {}
        chunks = self._chunking_service.chunk_blocks(page_blocks)
        for chunk in chunks:
            page = chunk.get("page_number")
            title = chunk.get("section_title")
            if page is not None and title and page not in titles_by_page:
                titles_by_page[page] = title
        return titles_by_page

    @staticmethod
    def _extract_header(content: str) -> list[str]:
        """Pull the column headers out of a markdown or row-format table chunk."""
        # Markdown: first line `| col1 | col2 |`
        if content.startswith("|"):
            first_line = content.splitlines()[0]
            return [c.strip() for c in first_line.strip().strip("|").split("|") if c.strip()]
        # Row format: `[Section: ...] [Table ...] col1: val | col2: val`
        # Strip the [Section: ...] [Table ...] prefix before splitting on `|` so the
        # prefix's bracket/colon characters don't pollute the first column name.
        body = re.sub(r"^\s*(\[Section:[^\]]*\]\s*)?\[Table\s+\S+\]\s*", "", content)
        if "|" in body:
            cells = body.split("|")
            return [c.split(":")[0].strip() for c in cells if ":" in c]
        return []
