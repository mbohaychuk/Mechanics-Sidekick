import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import ChatMessageIn, ChatMessageOut
from app.config import settings
from app.repositories.chat_repository import ChatRepository
from app.services.factories import make_chat_orchestrator

router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.get("/jobs/{job_id}/messages", response_model=list[ChatMessageOut])
def list_messages(job_id: int, session: Session = Depends(get_session)):
    return ChatRepository(session).list_by_job(job_id)


@router.post("/jobs/{job_id}/messages")
def send_message(job_id: int, payload: ChatMessageIn, request: Request):
    session_factory = request.app.state.session_factory

    def event_stream():
        session = session_factory()
        try:
            orchestrator = make_chat_orchestrator(session, settings)
            for event in orchestrator.run(job_id, payload.content):
                yield _sse(event)
            session.commit()
        except Exception as exc:  # surface, don't crash the stream
            yield _sse({"type": "error", "detail": str(exc)})
            session.rollback()
        finally:
            session.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
