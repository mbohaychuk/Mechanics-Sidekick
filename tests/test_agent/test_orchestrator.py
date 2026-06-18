from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import ProviderTurn, ToolCall
from app.models.vehicle import Vehicle
from app.models.job import Job
from app.repositories.chat_repository import ChatRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository


class FakeProvider:
    """Yields scripted turns: first a search_manuals tool call, then a final answer."""

    def __init__(self, turns):
        self._turns = list(turns)

    def stream_turn(self, messages, tools):
        turn = self._turns.pop(0)
        if turn.text and not turn.tool_calls:
            yield {"type": "token", "text": turn.text}
        yield {"type": "turn", "turn": turn}


def _seed(db_session):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    db_session.add(Job(vehicle_id=1, title="Brakes"))
    db_session.flush()


def _orchestrator(db_session, provider):
    retrieval = MagicMock()
    retrieval.retrieve.return_value = [
        (SimpleNamespace(document_id=1, page_number=10, content="Torque 40 Nm."), 0.9)
    ]
    doc_repo = MagicMock()
    doc_repo.get_by_id.return_value = SimpleNamespace(file_name="m.pdf")
    return AgentOrchestrator(
        chat_repo=ChatRepository(db_session),
        job_repo=JobRepository(db_session),
        vehicle_repo=VehicleRepository(db_session),
        doc_repo=doc_repo,
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=6,
        max_iters=6,
    )


def test_tool_then_answer_flow(db_session):
    _seed(db_session)
    provider = FakeProvider(
        [
            ProviderTurn(text="", tool_calls=[ToolCall("call_1", "search_manuals", {"query": "torque"})]),
            ProviderTurn(text="It is 40 Nm.", tool_calls=[]),
        ]
    )
    orch = _orchestrator(db_session, provider)

    events = list(orch.run(job_id=1, user_message="brake torque?"))
    types = [e["type"] for e in events]

    assert "tool_call" in types
    assert "tool_result" in types
    assert "token" in types
    assert types[-1] == "done"
    sources_event = next(e for e in events if e["type"] == "sources")
    assert sources_event["sources"][0]["filename"] == "m.pdf"

    history = ChatRepository(db_session).list_by_job(1)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "It is 40 Nm."


def test_unknown_job_yields_error(db_session):
    provider = FakeProvider([ProviderTurn(text="hi", tool_calls=[])])
    orch = _orchestrator(db_session, provider)
    events = list(orch.run(job_id=999, user_message="x"))
    assert events[0]["type"] == "error"
