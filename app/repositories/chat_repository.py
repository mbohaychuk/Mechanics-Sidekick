# app/repositories/chat_repository.py
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
        query = (
            self.session.query(ChatMessage)
            .filter(ChatMessage.job_id == job_id)
            .order_by(ChatMessage.id)
        )
        if limit is not None:
            total = query.count()
            offset = max(0, total - limit)
            query = query.offset(offset)
        return query.all()
