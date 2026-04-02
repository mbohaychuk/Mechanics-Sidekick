# app/models/chat_message.py
from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_utc: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    sources_json: Mapped[str | None] = mapped_column(Text, nullable=True)
