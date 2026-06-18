# Phase 2 — Agentic Chat (manuals-only) Implementation Plan

**Goal:** Replace the single-shot RAG chat with an agentic, tool-using chat: the model calls a `search_manuals` tool as it reasons, and the answer streams to the client over SSE, grounded in the vehicle's manuals.

**Architecture:** A new `app/agent/` package holds a provider seam (`ChatProvider` + `OpenAIProvider` with streaming tool-calls), a `search_manuals` tool wrapping the existing `RetrievalService`, and an `AgentOrchestrator` that runs the tool-calling loop and yields stream events. A new SSE endpoint (`POST /api/jobs/{id}/messages`) drives the orchestrator inside its own DB session; a history endpoint lists prior messages. The existing services/repositories are reused unchanged.

**Tech Stack:** Python 3.11+, FastAPI (StreamingResponse/SSE), OpenAI Python SDK (streaming + function-calling), SQLAlchemy 2.0, pytest + FastAPI `TestClient`.

This is Plan 2 of the phased v1 work (Plan 1 backend foundation is merged). It produces working software: an agentic chat API over the manuals. obd-mcp tools + web search are Plan 3; the Vue SPA is Plan 4.

## Global Constraints

- Python ≥ 3.11; deps via `uv`; run via `uv run`.
- All HTTP routes under `/api`. The chat stream is `text/event-stream` (SSE): each event is one line `data: <json>\n\n`.
- OpenAI is the chat provider (function-calling). The provider seam keeps a single implementation (`OpenAIProvider`); no second provider in this plan.
- The orchestrator and provider are synchronous (the OpenAI client and DB are sync). The SSE endpoint streams a sync generator via `StreamingResponse` (Starlette runs it in a threadpool — do not block the event loop with an async wrapper around blocking I/O).
- The orchestrator manages its OWN DB session (from `app.state.session_factory`) for the duration of the stream — it must NOT use the request-scoped `get_session` dependency, whose session is torn down before the stream body runs.
- Persist only `user` and final `assistant` messages (+ `sources_json`), reusing the existing `chat_message` table — NO schema migration. Tool activity is streamed live, not persisted.
- Tests never hit the network: the OpenAI provider and embeddings are faked/mocked. Full suite (`uv run pytest tests/ -v`) stays green and pristine. The existing CLI + 83 tests must not break.
- No AI/Claude attribution in commit messages; no AI-tooling names in tracked content.

---

### Task 1: ChatProvider seam + OpenAIProvider (streaming tool-calls)

**Files:**
- Create: `app/agent/__init__.py` (empty)
- Create: `app/agent/provider.py`
- Test: `tests/test_agent/__init__.py` (empty), `tests/test_agent/test_provider.py`

**Interfaces:**
- Produces:
  - `ToolCall` dataclass: `id: str`, `name: str`, `arguments: dict`.
  - `ProviderTurn` dataclass: `text: str`, `tool_calls: list[ToolCall]`.
  - `ChatProvider` Protocol: `stream_turn(messages: list[dict], tools: list[dict]) -> Iterator[dict]` — yields `{"type":"token","text":str}` events during content, then exactly one terminal `{"type":"turn","turn":ProviderTurn}`.
  - `OpenAIProvider(api_key: str | None, model: str, client=None)` implementing `ChatProvider` over `client.chat.completions.create(..., stream=True)`.

- [x] **Step 1: Write the failing test**

Create `tests/test_agent/__init__.py` (empty).

Create `tests/test_agent/test_provider.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.provider import OpenAIProvider, ProviderTurn, ToolCall


def _content_chunk(text):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _toolcall_chunk(index, *, id=None, name=None, args=None):
    fn = SimpleNamespace(name=name, arguments=args)
    tcd = SimpleNamespace(index=index, id=id, function=fn)
    delta = SimpleNamespace(content=None, tool_calls=[tcd])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_streams_text_tokens_then_turn():
    client = MagicMock()
    client.chat.completions.create.return_value = iter(
        [_content_chunk("Hel"), _content_chunk("lo")]
    )
    provider = OpenAIProvider(api_key="x", model="gpt-4.1-mini", client=client)

    events = list(provider.stream_turn([{"role": "user", "content": "hi"}], []))

    assert events[0] == {"type": "token", "text": "Hel"}
    assert events[1] == {"type": "token", "text": "lo"}
    assert events[-1]["type"] == "turn"
    turn = events[-1]["turn"]
    assert isinstance(turn, ProviderTurn)
    assert turn.text == "Hello"
    assert turn.tool_calls == []


def test_accumulates_tool_call_across_chunks():
    client = MagicMock()
    client.chat.completions.create.return_value = iter(
        [
            _toolcall_chunk(0, id="call_1", name="search_manuals", args='{"qu'),
            _toolcall_chunk(0, args='ery": "brakes"}'),
        ]
    )
    provider = OpenAIProvider(api_key="x", model="gpt-4.1-mini", client=client)

    events = list(provider.stream_turn([{"role": "user", "content": "hi"}], [{"x": 1}]))

    turn = events[-1]["turn"]
    assert turn.text == ""
    assert turn.tool_calls == [
        ToolCall(id="call_1", name="search_manuals", arguments={"query": "brakes"})
    ]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent/test_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.provider`.

- [x] **Step 3: Write the implementation**

Create `app/agent/__init__.py` (empty).

Create `app/agent/provider.py`:
```python
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from openai import OpenAI


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatProvider(Protocol):
    def stream_turn(self, messages: list[dict], tools: list[dict]) -> Iterator[dict]:
        """Yield {"type": "token", "text": str} events during content, then
        exactly one terminal {"type": "turn", "turn": ProviderTurn}."""
        ...


class OpenAIProvider:
    def __init__(self, api_key: str | None, model: str, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=api_key)
        self._model = model

    def stream_turn(self, messages: list[dict], tools: list[dict]) -> Iterator[dict]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            stream=True,
        )
        text_parts: list[str] = []
        acc: dict[int, dict] = {}
        for chunk in stream:
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                text_parts.append(delta.content)
                yield {"type": "token", "text": delta.content}
            for tcd in getattr(delta, "tool_calls", None) or []:
                slot = acc.setdefault(tcd.index, {"id": "", "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments
        tool_calls: list[ToolCall] = []
        for idx in sorted(acc):
            slot = acc[idx]
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], arguments=args))
        yield {"type": "turn", "turn": ProviderTurn(text="".join(text_parts), tool_calls=tool_calls)}
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent/test_provider.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/agent/__init__.py app/agent/provider.py tests/test_agent
git commit -m "feat(agent): streaming OpenAI chat provider with tool-call accumulation"
```

---

### Task 2: search_manuals tool

**Files:**
- Create: `app/agent/tools.py`
- Test: `tests/test_agent/test_tools.py`

**Interfaces:**
- Consumes: existing `RetrievalService.retrieve(vehicle_id, question) -> list[tuple[DocumentChunk, float]]`, `DocumentRepository.get_by_id`.
- Produces:
  - `SEARCH_MANUALS_TOOL: dict` — an OpenAI function-tool schema with name `search_manuals` and a required string `query`.
  - `execute_search_manuals(retrieval, doc_repo, vehicle_id, query) -> dict` returning `{"sources": [{"filename","page","score"}], "model_text": str}`.

- [x] **Step 1: Write the failing test**

Create `tests/test_agent/test_tools.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.tools import SEARCH_MANUALS_TOOL, execute_search_manuals


def test_tool_schema_shape():
    assert SEARCH_MANUALS_TOOL["type"] == "function"
    fn = SEARCH_MANUALS_TOOL["function"]
    assert fn["name"] == "search_manuals"
    assert "query" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["query"]


def test_execute_maps_chunks_to_sources_and_text():
    chunk = SimpleNamespace(document_id=7, page_number=42, content="Torque is 40 Nm.")
    retrieval = MagicMock()
    retrieval.retrieve.return_value = [(chunk, 0.91234)]
    doc_repo = MagicMock()
    doc_repo.get_by_id.return_value = SimpleNamespace(file_name="manual.pdf")

    result = execute_search_manuals(retrieval, doc_repo, vehicle_id=1, query="torque")

    retrieval.retrieve.assert_called_once_with(vehicle_id=1, question="torque")
    assert result["sources"] == [{"filename": "manual.pdf", "page": 42, "score": 0.9123}]
    assert "manual.pdf" in result["model_text"]
    assert "Torque is 40 Nm." in result["model_text"]


def test_execute_empty_results():
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    result = execute_search_manuals(retrieval, MagicMock(), vehicle_id=1, query="x")
    assert result["sources"] == []
    assert "No relevant" in result["model_text"]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.tools`.

- [x] **Step 3: Write the implementation**

Create `app/agent/tools.py`:
```python
from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import RetrievalService

SEARCH_MANUALS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_manuals",
        "description": (
            "Search the uploaded service manuals for this vehicle. Use this to ground every "
            "factual answer (specifications, torque values, fluid types, procedures) in the "
            "manuals before answering. Returns the most relevant excerpts with their source "
            "filename and page number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, e.g. 'front brake caliper torque spec'.",
                }
            },
            "required": ["query"],
        },
    },
}


def execute_search_manuals(
    retrieval: RetrievalService,
    doc_repo: DocumentRepository,
    vehicle_id: int,
    query: str,
) -> dict:
    ranked = retrieval.retrieve(vehicle_id=vehicle_id, question=query)
    sources: list[dict] = []
    excerpts: list[str] = []
    for i, (chunk, score) in enumerate(ranked, start=1):
        doc = doc_repo.get_by_id(chunk.document_id)
        filename = doc.file_name if doc else f"document_{chunk.document_id}"
        page = chunk.page_number
        sources.append({"filename": filename, "page": page, "score": round(score, 4)})
        page_label = f"page {page}" if page is not None else "page unknown"
        excerpts.append(f"[{i}] {filename}, {page_label}:\n{chunk.content}")
    model_text = "\n\n".join(excerpts) if excerpts else "No relevant excerpts found in the manuals."
    return {"sources": sources, "model_text": model_text}
```

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent/test_tools.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/agent/tools.py tests/test_agent/test_tools.py
git commit -m "feat(agent): search_manuals tool over RetrievalService"
```

---

### Task 3: AgentOrchestrator (tool-calling loop) + config

**Files:**
- Create: `app/agent/orchestrator.py`
- Modify: `app/config.py` (add `max_agent_iters`)
- Test: `tests/test_agent/test_orchestrator.py`

**Interfaces:**
- Consumes: `ChatProvider` (Task 1), `SEARCH_MANUALS_TOOL`/`execute_search_manuals` (Task 2), existing repositories, `RetrievalService`.
- Produces: `AgentOrchestrator(chat_repo, job_repo, vehicle_repo, doc_repo, retrieval, provider, recent_messages_limit=6, max_iters=6)` with `run(job_id: int, user_message: str) -> Iterator[dict]` yielding events of types `token`, `tool_call`, `tool_result`, `sources`, `done`, `error`. Persists the user message and the final assistant message (+ `sources_json`).
- Produces: `Settings.max_agent_iters: int = 6`.

- [x] **Step 1: Write the failing test**

Create `tests/test_agent/test_orchestrator.py`:
```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.orchestrator`.

- [x] **Step 3: Add the config field**

In `app/config.py`, add after `recent_messages`:
```python
    max_agent_iters: int = 6
```

- [x] **Step 4: Write the orchestrator**

Create `app/agent/orchestrator.py`:
```python
from __future__ import annotations

import json
from collections.abc import Iterator

from app.agent.provider import ChatProvider, ToolCall
from app.agent.tools import SEARCH_MANUALS_TOOL, execute_search_manuals
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.retrieval_service import RetrievalService

SYSTEM_PROMPT = (
    "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance. "
    "The vehicle is: {vehicle}. "
    "Use the search_manuals tool to look up specifications, torque values, fluid types, and "
    "procedures in the uploaded service manuals before answering factual questions. Never invent "
    "specs or procedures — if the manuals do not cover it, say so plainly. Keep answers concise and "
    "mechanic-friendly, and cite the source filename and page for any specification you give."
)


class AgentOrchestrator:
    def __init__(
        self,
        chat_repo: ChatRepository,
        job_repo: JobRepository,
        vehicle_repo: VehicleRepository,
        doc_repo: DocumentRepository,
        retrieval: RetrievalService,
        provider: ChatProvider,
        recent_messages_limit: int = 6,
        max_iters: int = 6,
    ) -> None:
        self._chat_repo = chat_repo
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo
        self._doc_repo = doc_repo
        self._retrieval = retrieval
        self._provider = provider
        self._recent_limit = recent_messages_limit
        self._max_iters = max_iters

    def run(self, job_id: int, user_message: str) -> Iterator[dict]:
        job = self._job_repo.get_by_id(job_id)
        if job is None:
            yield {"type": "error", "detail": f"Job {job_id} not found"}
            return
        vehicle = self._vehicle_repo.get_by_id(job.vehicle_id)
        if vehicle is None:
            yield {"type": "error", "detail": f"Vehicle {job.vehicle_id} not found"}
            return

        recent = self._chat_repo.list_by_job(job_id, limit=self._recent_limit)
        self._chat_repo.create(job_id=job_id, role="user", content=user_message)

        vehicle_label = f"{vehicle.year} {vehicle.make} {vehicle.model}, engine {vehicle.engine}"
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(vehicle=vehicle_label)},
            {"role": "system", "content": f"Current job: {job.title}"},
        ]
        for m in recent:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_message})

        tools = [SEARCH_MANUALS_TOOL]
        sources: list[dict] = []

        for _ in range(self._max_iters):
            turn = None
            for ev in self._provider.stream_turn(messages, tools):
                if ev["type"] == "token":
                    yield ev
                elif ev["type"] == "turn":
                    turn = ev["turn"]
            if turn is None:
                break

            if turn.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.text or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            }
                            for tc in turn.tool_calls
                        ],
                    }
                )
                for tc in turn.tool_calls:
                    yield {"type": "tool_call", "name": tc.name, "arguments": tc.arguments}
                    result = self._execute(tc, job.vehicle_id)
                    if tc.name == "search_manuals":
                        sources.extend(result["sources"])
                    yield {"type": "tool_result", "name": tc.name}
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result["model_text"]}
                    )
                continue

            final = turn.text or ""
            if sources:
                yield {"type": "sources", "sources": sources}
            self._chat_repo.create(
                job_id=job_id, role="assistant", content=final, sources_json=json.dumps(sources)
            )
            yield {"type": "done"}
            return

        fallback = "I was not able to complete this within the allowed number of steps."
        self._chat_repo.create(
            job_id=job_id, role="assistant", content=fallback, sources_json=json.dumps(sources)
        )
        yield {"type": "error", "detail": "max_iterations_reached"}
        yield {"type": "done"}

    def _execute(self, tc: ToolCall, vehicle_id: int) -> dict:
        if tc.name == "search_manuals":
            return execute_search_manuals(
                self._retrieval, self._doc_repo, vehicle_id, tc.arguments.get("query", "")
            )
        return {"sources": [], "model_text": f"Unknown tool: {tc.name}"}
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent/test_orchestrator.py -v`
Expected: PASS (both tests).

- [x] **Step 6: Commit**

```bash
git add app/agent/orchestrator.py app/config.py tests/test_agent/test_orchestrator.py
git commit -m "feat(agent): orchestrator tool-calling loop with manual-grounded answers"
```

---

### Task 4: SSE chat endpoint + history + factory wiring

**Files:**
- Modify: `app/services/factories.py` (add `make_chat_orchestrator`)
- Modify: `app/api/schemas.py` (add `ChatMessageIn`, `ChatMessageOut`)
- Create: `app/api/routers/chat.py`
- Modify: `app/api/main.py` (include the chat router)
- Test: `tests/test_api/test_chat.py`

**Interfaces:**
- Consumes: `AgentOrchestrator` (Task 3), the existing `make_embedding_service` (factories), `OpenAIProvider` (Task 1), `RetrievalService`, repositories, `get_session`.
- Produces:
  - `make_chat_orchestrator(session, settings) -> AgentOrchestrator`.
  - Schemas `ChatMessageIn{content: str}`, `ChatMessageOut{id, job_id, role, content, sources_json, created_utc}`.
  - Routes `POST /api/jobs/{job_id}/messages` → `text/event-stream`; `GET /api/jobs/{job_id}/messages` → message history.

- [x] **Step 1: Write the failing test**

Create `tests/test_api/test_chat.py`:
```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_chat.py -v`
Expected: FAIL — chat route not defined (404) / `make_chat_orchestrator` missing.

- [x] **Step 3: Add the factory**

In `app/services/factories.py`, add these imports at the top (with the others):
```python
from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import OpenAIProvider
from app.repositories.chat_repository import ChatRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.retrieval_service import RetrievalService
```
And append:
```python
def make_chat_orchestrator(session, settings: Settings) -> AgentOrchestrator:
    retrieval = RetrievalService(
        ChunkRepository(session),
        make_embedding_service(settings),
        settings.top_k_chunks,
    )
    provider = OpenAIProvider(
        api_key=settings.openai_api_key or None,
        model=settings.openai_chat_model,
    )
    return AgentOrchestrator(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=settings.recent_messages,
        max_iters=settings.max_agent_iters,
    )
```

- [x] **Step 4: Add the schemas**

Append to `app/api/schemas.py`:
```python
class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    role: str
    content: str
    sources_json: str | None
    created_utc: datetime
```

- [x] **Step 5: Write the chat router**

Create `app/api/routers/chat.py`:
```python
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
```

- [x] **Step 6: Include the router**

In `app/api/main.py`, add `chat` to the routers import and include it:
```python
from app.api.routers import vehicles, jobs, documents, chat
```
```python
    app.include_router(vehicles.router)
    app.include_router(jobs.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
```

- [x] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_chat.py -v`
Expected: PASS.

- [x] **Step 8: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS (all existing + new), pristine.

- [x] **Step 9: Commit**

```bash
git add app/services/factories.py app/api/schemas.py app/api/routers/chat.py app/api/main.py tests/test_api/test_chat.py
git commit -m "feat(api): SSE agentic chat endpoint and message history"
```

---

## Manual smoke test (after all tasks)

With a real `OPENAI_API_KEY` and a vehicle that has ingested manuals:
```bash
uv run mechanic-sidekick-api
# create a vehicle + job (or reuse), then:
curl -N -X POST localhost:8000/api/jobs/1/messages \
  -H 'content-type: application/json' \
  -d '{"content":"What is the front brake caliper torque spec?"}'
# expect a text/event-stream: token… tool_call(search_manuals) tool_result sources done
curl -s localhost:8000/api/jobs/1/messages   # user + assistant rows
```

## Self-review

**Spec coverage (design spec §1.3 agentic chat, §1.4 data flow, §1.11 chat routes):**
- Provider seam + OpenAIProvider streaming tool-calls → Task 1. ✔
- search_manuals tool over RetrievalService → Task 2. ✔
- Orchestrator loop (system prompt, history, tool loop, iteration cap, sources, persistence) → Task 3. ✔
- SSE `POST /api/jobs/{id}/messages` + `GET` history + factory + wiring → Task 4. ✔
- No schema migration (reuse chat_message); tool activity streamed not persisted → Task 3/4. ✔
- Out of scope (Plan 3+): obd-mcp tools, web_search, the Vue SPA. Correctly excluded.

**Placeholder scan:** none — every step has full code and assertions. ✔

**Type consistency:** `ProviderTurn`/`ToolCall` fields and `stream_turn`'s `{"type":"token"|"turn"}` event shape are identical across Tasks 1, 3, 4 and their tests. `execute_search_manuals` signature matches between Task 2 (def) and Task 3 (call) and Task 4's monkeypatch. `make_chat_orchestrator(session, settings)` matches between Task 4 def and the chat router call. ✔
