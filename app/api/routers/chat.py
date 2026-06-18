import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import ChatMessageIn, ChatMessageOut
from app.config import settings
from app.repositories.chat_repository import ChatRepository
from app.services.factories import make_chat_orchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.get("/jobs/{job_id}/messages", response_model=list[ChatMessageOut])
def list_messages(job_id: int, session: Session = Depends(get_session)):
    return ChatRepository(session).list_by_job(job_id)


@router.post("/jobs/{job_id}/messages")
def send_message(job_id: int, payload: ChatMessageIn, request: Request):
    session_factory = request.app.state.session_factory

    # get_session can't be used here: FastAPI closes Depends() generator sessions when the
    # handler returns, which is before the StreamingResponse body is iterated. Own the session.
    def event_stream():
        session = session_factory()
        try:
            orchestrator = make_chat_orchestrator(session, settings)
            for event in orchestrator.run(job_id, payload.content):
                yield _sse(event)
            session.commit()
        except Exception:
            logger.exception("Unhandled error in chat stream for job %s", job_id)
            yield _sse({"type": "error", "detail": "An internal error occurred."})
            session.rollback()
        finally:
            session.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
