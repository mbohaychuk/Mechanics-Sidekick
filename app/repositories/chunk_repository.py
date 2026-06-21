# app/repositories/chunk_repository.py
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import FTS_TABLE
from app.models.document import Document
from app.models.document_chunk import DocumentChunk

_TOKEN_RE = re.compile(r"[\w./-]+")


def _to_match_query(question: str) -> str:
    """Build an FTS5 MATCH string: each query token phrase-quoted and OR-joined. Phrase quotes
    are mandatory — a raw `MATCH 'M12x1.5'` / `'lb-ft'` throws a syntax error; quoting also lets
    BM25 rank by term overlap so rare tokens (DTC codes, part numbers) dominate the score."""
    tokens = _TOKEN_RE.findall(question)
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else ""


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, chunks: list[DocumentChunk]) -> None:
        self.session.add_all(chunks)
        if not chunks:
            return
        self.session.flush()  # assign ids so the FTS rows can key on them
        self.session.execute(
            text(f"INSERT INTO {FTS_TABLE}(rowid, content, section_title) "
                 "VALUES (:rowid, :content, :section_title)"),
            [{"rowid": c.id, "content": c.content, "section_title": c.section_title or ""} for c in chunks],
        )

    def delete_by_document(self, document_id: int) -> None:
        # Clear the contentful FTS rows first (plain delete by rowid — no orphan), then the chunks.
        self.session.execute(
            text(f"DELETE FROM {FTS_TABLE} WHERE rowid IN "
                 "(SELECT id FROM document_chunks WHERE document_id = :doc)"),
            {"doc": document_id},
        )
        (
            self.session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .delete(synchronize_session=False)
        )

    def list_by_vehicle(self, vehicle_id: int) -> list[DocumentChunk]:
        """Return all chunks from ready documents belonging to this vehicle."""
        return (
            self.session.query(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.vehicle_id == vehicle_id)
            .filter(Document.processing_status == "ready")
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )

    def search_fts(self, vehicle_id: int, question: str, limit: int) -> list[int]:
        """BM25 keyword search, returning chunk ids ranked best-first. Scoped to this vehicle's
        READY documents — FTS MATCH is global, so the scope must be re-applied here or other
        vehicles' / half-ingested chunks leak in."""
        match = _to_match_query(question)
        if not match:
            return []
        rows = self.session.execute(
            text(
                f"SELECT cf.rowid FROM {FTS_TABLE} cf "
                f"WHERE {FTS_TABLE} MATCH :q "
                "AND cf.rowid IN ("
                "  SELECT dc.id FROM document_chunks dc "
                "  JOIN documents d ON dc.document_id = d.id "
                "  WHERE d.vehicle_id = :vid AND d.processing_status = 'ready'"
                ") ORDER BY rank LIMIT :lim"
            ),
            {"q": match, "vid": vehicle_id, "lim": limit},
        ).all()
        return [row[0] for row in rows]
