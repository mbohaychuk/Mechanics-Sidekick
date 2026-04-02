# app/repositories/chat_repository.py
from sqlalchemy import desc
from sqlalchemy.orm import Session
from app.models.chat_message import ChatMessage


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        job_id: int,
        role: str,
        content: str,
        sources_json: str | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(job_id=job_id, role=role, content=content, sources_json=sources_json)
        self.session.add(msg)
        return msg

    def list_by_job(self, job_id: int, limit: int | None = None) -> list[ChatMessage]:
        if limit is not None:
            rows = (
                self.session.query(ChatMessage)
                .filter(ChatMessage.job_id == job_id)
                .order_by(desc(ChatMessage.id))
                .limit(limit)
                .all()
            )
            return list(reversed(rows))
        return (
            self.session.query(ChatMessage)
            .filter(ChatMessage.job_id == job_id)
            .order_by(ChatMessage.id)
            .all()
        )
