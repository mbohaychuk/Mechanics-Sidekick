import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.provider import ProviderTurn, ToolCall
from app.models.job import Job
from app.models.vehicle import Vehicle


class _FakeProvider:
    def __init__(self, *args, **kwargs):
        self._turns = [
            ProviderTurn(text="", tool_calls=[ToolCall("c1", "search_manuals", {"query": "oil"})]),
            ProviderTurn(text="Use 5W-30.", tool_calls=[]),
        ]

    def stream_turn(self, messages, tools):
        turn = self._turns.pop(0)
        if turn.text and not turn.tool_calls:
            yield {"type": "token", "text": turn.text}
        yield {"type": "turn", "turn": turn}


def _fake_embedding():
    emb = MagicMock()
    emb.embed_query.return_value = [0.0, 1.0]
    return emb


def _seed_vehicle_job(api_client):
    factory = api_client.app.state.session_factory
    session = factory()
    try:
        session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
        session.flush()
        session.add(Job(vehicle_id=1, title="Oil change"))
        session.commit()
    finally:
        session.close()


def test_chat_streams_events_and_persists(api_client, monkeypatch):
    _seed_vehicle_job(api_client)
    # Fake the OpenAI provider and the embedding backend so nothing hits the network.
    monkeypatch.setattr("app.services.factories.OpenAIProvider", _FakeProvider)
    monkeypatch.setattr("app.services.factories.make_embedding_service", lambda s: _fake_embedding())
    # retrieval returns no chunks (search_manuals still runs; sources may be empty)
    monkeypatch.setattr(
        "app.agent.tools.execute_search_manuals",
        lambda retrieval, doc_repo, vehicle_id, query: {
            "sources": [{"filename": "m.pdf", "page": 3, "score": 0.9}],
            "model_text": "[1] m.pdf, page 3:\n5W-30 recommended.",
        },
    )

    r = api_client.post("/api/jobs/1/messages", json={"content": "what oil?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = [json.loads(line[len("data: "):]) for line in r.text.splitlines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    assert "token" in types
    assert types[-1] == "done"

    history = api_client.get("/api/jobs/1/messages")
    assert history.status_code == 200
    rows = history.json()
    assert [m["role"] for m in rows] == ["user", "assistant"]
    assert rows[1]["content"] == "Use 5W-30."


def test_chat_error_event_on_orchestrator_failure(api_client, monkeypatch):
    _seed_vehicle_job(api_client)

    class _Boom:
        def run(self, *a, **k):
            raise RuntimeError("kaboom")
            yield  # make it a generator

    monkeypatch.setattr("app.api.routers.chat.make_chat_orchestrator", lambda session, settings: _Boom())
    r = api_client.post("/api/jobs/1/messages", json={"content": "x"})
    assert r.status_code == 200
    assert '"type": "error"' in r.text
    assert "An internal error occurred." in r.text
