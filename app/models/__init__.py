# app/models/__init__.py
from app.models.vehicle import Vehicle
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.chat_message import ChatMessage

__all__ = ["Vehicle", "Document", "DocumentChunk", "Job", "ChatMessage"]
