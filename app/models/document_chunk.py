# app/models/document_chunk.py
from sqlalchemy import ForeignKey, Text, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int] = mapped_column()
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    content: Mapped[str] = mapped_column(Text)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_kind: Mapped[str] = mapped_column(String(16), default="prose")
    engine_variant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
