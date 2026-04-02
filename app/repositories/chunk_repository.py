# app/repositories/chunk_repository.py
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.document_chunk import DocumentChunk


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, chunks: list[DocumentChunk]) -> None:
        self.session.add_all(chunks)

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
