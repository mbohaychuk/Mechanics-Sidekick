# app/repositories/chunk_repository.py
"""Owns the invariant that every chunk lives in three tables.

A chunk row in document_chunks is paired with:
  - a document_chunks_fts row (BM25 over the contextualized text)
  - a document_chunks_vec row (cosine over the embedding)

bulk_create takes ChunkInsert records carrying all three pieces so callers
cannot forget one. Plan 2's HybridRetrievalService reads these tables.
"""
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk


@dataclass
class ChunkInsert:
    """Single chunk to bulk-insert: row data + the text BM25 indexes + the embedding vec."""
    chunk: DocumentChunk
    indexable_text: str
    embedding: list[float]


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, inserts: list[ChunkInsert]) -> None:
        if not inserts:
            return
        # 1. Insert main rows; flush to populate auto-increment ids.
        self.session.add_all([ins.chunk for ins in inserts])
        self.session.flush()

        # 2. Mirror to the FTS5 and vec0 virtual tables.
        for ins in inserts:
            self.session.execute(
                text("INSERT INTO document_chunks_fts (chunk_id, text) VALUES (:cid, :txt)"),
                {"cid": ins.chunk.id, "txt": ins.indexable_text},
            )
            self.session.execute(
                text("INSERT INTO document_chunks_vec (chunk_id, embedding) VALUES (:cid, :emb)"),
                {"cid": ins.chunk.id, "emb": _serialize_vec(ins.embedding)},
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


def _serialize_vec(embedding: list[float]) -> bytes:
    """sqlite-vec accepts a list of floats encoded as little-endian float32 bytes."""
    import struct
    return struct.pack(f"{len(embedding)}f", *embedding)
