from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import ProviderTurn, ToolCall
from app.models.vehicle import Vehicle
from app.models.job import Job
from app.repositories.chat_repository import ChatRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository


class FakeProvider:
    """Replays a fixed list of ProviderTurn objects, one per stream_turn call."""

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


def _orchestrator(db_session, provider, max_iters=6, obd_host=None, web_search_client=None, vehicle_repo=None):
    retrieval = MagicMock()
    retrieval.retrieve.return_value = [
        (SimpleNamespace(document_id=1, page_number=10, content="Torque 40 Nm."), 0.9)
    ]
    doc_repo = MagicMock()
    doc_repo.get_by_id.return_value = SimpleNamespace(file_name="m.pdf")
    return AgentOrchestrator(
        chat_repo=ChatRepository(db_session),
        job_repo=JobRepository(db_session),
        vehicle_repo=vehicle_repo or VehicleRepository(db_session),
        doc_repo=doc_repo,
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=6,
        max_iters=max_iters,
        obd_host=obd_host,
        web_search_client=web_search_client,
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
    assert ChatRepository(db_session).list_by_job(999) == []


class InfiniteToolCallProvider:
    """Always yields a tool-call turn; never terminates with final text."""

    def stream_turn(self, messages, tools):
        yield {
            "type": "turn",
            "turn": ProviderTurn(
                text="", tool_calls=[ToolCall("c", "search_manuals", {"query": "x"})]
            ),
        }


def test_iteration_cap(db_session):
    _seed(db_session)
    provider = InfiniteToolCallProvider()
    orch = _orchestrator(db_session, provider, max_iters=2)

    events = list(orch.run(job_id=1, user_message="query"))
    types = [e["type"] for e in events]

    assert "error" in types
    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["detail"] == "max_iterations_reached"
    assert types[-1] == "done"

    history = ChatRepository(db_session).list_by_job(1)
    assert [m.role for m in history] == ["user", "assistant"]


def test_missing_vehicle(db_session):
    # FK enforcement guarantees a job's vehicle row exists, so the orchestrator's defensive
    # "vehicle is None" branch is reachable only via an inconsistent lookup — simulate that
    # with a vehicle_repo that reports the (seeded, FK-valid) vehicle missing.
    _seed(db_session)
    job_id = db_session.query(Job).first().id

    vehicle_repo = MagicMock()
    vehicle_repo.get_by_id.return_value = None
    provider = FakeProvider([ProviderTurn(text="hi", tool_calls=[])])
    orch = _orchestrator(db_session, provider, vehicle_repo=vehicle_repo)

    events = list(orch.run(job_id=job_id, user_message="query"))
    assert events[0]["type"] == "error"
    assert "Vehicle 1" in events[0]["detail"]

    history = ChatRepository(db_session).list_by_job(job_id)
    assert history == []


def test_tool_failure_degrades_and_loop_continues(db_session):
    _seed(db_session)
    job_id = db_session.query(Job).first().id
    provider = FakeProvider([
        ProviderTurn(text="", tool_calls=[ToolCall(id="c1", name="search_manuals", arguments={"query": "x"})]),
        ProviderTurn(text="Here is my answer.", tool_calls=[]),
    ])
    orch = _orchestrator(db_session, provider)
    orch._retrieval.retrieve.side_effect = RuntimeError("boom")  # the tool blows up

    events = list(orch.run(job_id=job_id, user_message="q"))

    assert "tool_result" in [e["type"] for e in events]   # tool ran and soft-failed
    assert events[-1]["type"] == "done"                    # the turn still completed
    history = ChatRepository(db_session).list_by_job(job_id)
    assert any(m.role == "assistant" and "answer" in m.content.lower() for m in history)


def test_multiple_tool_calls_in_one_turn(db_session):
    # A single turn returning >1 tool_call must execute each and pair tool results by id.
    _seed(db_session)
    job_id = db_session.query(Job).first().id
    provider = FakeProvider([
        ProviderTurn(text="", tool_calls=[
            ToolCall(id="a", name="search_manuals", arguments={"query": "brakes"}),
            ToolCall(id="b", name="search_manuals", arguments={"query": "oil"}),
        ]),
        ProviderTurn(text="Done.", tool_calls=[]),
    ])
    orch = _orchestrator(db_session, provider)

    events = list(orch.run(job_id=job_id, user_message="q"))

    assert len([e for e in events if e["type"] == "tool_result"]) == 2  # both executed
    assert events[-1]["type"] == "done"


class _ExplodingProvider:
    def stream_turn(self, messages, tools):
        raise RuntimeError("network down")
        yield  # unreachable — marks this as a generator


def test_provider_failure_persists_assistant_turn(db_session):
    _seed(db_session)
    job_id = db_session.query(Job).first().id
    orch = _orchestrator(db_session, _ExplodingProvider())

    events = list(orch.run(job_id=job_id, user_message="q"))

    assert any(e["type"] == "error" and "provider_error" in e["detail"] for e in events)
    error_text = " ".join(e.get("detail", "") for e in events if e["type"] == "error")
    assert "network down" not in error_text  # raw exception text must NOT leak to the client
    roles = [m.role for m in ChatRepository(db_session).list_by_job(job_id)]
    assert roles == ["user", "assistant"]  # no silent half-written conversation


class CapturingProvider:
    """Like FakeProvider, but records the tool names advertised on each turn."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.seen_tool_names = []

    def stream_turn(self, messages, tools):
        self.seen_tool_names.append([t["function"]["name"] for t in tools])
        turn = self._turns.pop(0)
        if turn.text and not turn.tool_calls:
            yield {"type": "token", "text": turn.text}
        yield {"type": "turn", "turn": turn}


class FakeObdHost:
    def __init__(self, available=True, tools=None, responses=None):
        self.available = available
        self._tools = tools or [
            {
                "type": "function",
                "function": {
                    "name": "read_dtcs",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        self._responses = responses or {"read_dtcs": '{"codes": ["P0301"]}'}
        self.calls = []

    def openai_tools(self):
        return list(self._tools) if self.available else []

    def handles(self, name):
        return self.available and name in {t["function"]["name"] for t in self._tools}

    def call(self, name, args):
        self.calls.append((name, args))
        return self._responses.get(name, "[obd error] unknown")


def test_obd_tool_advertised_and_dispatched(db_session):
    _seed(db_session)
    host = FakeObdHost()
    provider = CapturingProvider(
        [
            ProviderTurn(text="", tool_calls=[ToolCall("c1", "read_dtcs", {})]),
            ProviderTurn(text="You have a P0301 misfire.", tool_calls=[]),
        ]
    )
    orch = _orchestrator(db_session, provider, obd_host=host)

    events = list(orch.run(job_id=1, user_message="any codes?"))
    types = [e["type"] for e in events]

    assert "read_dtcs" in provider.seen_tool_names[0]
    assert "search_manuals" in provider.seen_tool_names[0]
    assert host.calls == [("read_dtcs", {})]
    assert "tool_call" in types and "tool_result" in types
    history = ChatRepository(db_session).list_by_job(1)
    assert history[1].content == "You have a P0301 misfire."


def test_obd_unavailable_degrades_to_manuals_only(db_session):
    _seed(db_session)
    host = FakeObdHost(available=False)
    provider = CapturingProvider([ProviderTurn(text="No scanner connected.", tool_calls=[])])
    orch = _orchestrator(db_session, provider, obd_host=host)

    list(orch.run(job_id=1, user_message="any codes?"))

    assert provider.seen_tool_names[0] == ["search_manuals"]  # no OBD tools advertised


def test_web_search_advertised_and_dispatched(db_session):
    _seed(db_session)
    web_client = MagicMock()
    web_client.search.return_value = {"answer": "Known issue.", "results": []}
    provider = CapturingProvider(
        [
            ProviderTurn(text="", tool_calls=[ToolCall("c1", "web_search", {"query": "recall"})]),
            ProviderTurn(text="There is a recall.", tool_calls=[]),
        ]
    )
    orch = _orchestrator(db_session, provider, web_search_client=web_client)

    list(orch.run(job_id=1, user_message="any recalls?"))

    assert "web_search" in provider.seen_tool_names[0]
    web_client.search.assert_called_once()
