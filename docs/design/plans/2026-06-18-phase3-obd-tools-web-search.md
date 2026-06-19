# Phase 3 — Live OBD Tools (obd-mcp host) + Web Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agentic chat two new tool families — read-only live OBD-II tools served by the separate `obd-mcp` project (connected over stdio), and a `web_search` tool — so the model can read the car and the public web, then ground answers in the manuals it already searches.

**Architecture:** A new `app/agent/mcp_host.py` spawns `obd-mcp` as a stdio child and owns a long-lived MCP `ClientSession` on a dedicated asyncio event-loop thread; it exposes a **synchronous** surface (`available`, `openai_tools()`, `handles()`, `call()`) so the existing sync orchestrator and SSE generator can use it without touching asyncio. The host filters out destructive (and denylisted) tools at connect time. The orchestrator's tool list and `_execute` dispatch are extended to include the host's OBD tools and a Tavily-backed `web_search`. The host is a process-lifetime singleton started in the FastAPI lifespan and stored on `app.state.obd_host`; a new `GET /api/scanner/status` reports its state. Everything degrades gracefully: if `obd-mcp` is disabled or fails to start, chat runs with manuals + web only.

**Tech Stack:** Python 3.11+, the official MCP Python SDK (`mcp`, pinned `>=1.28,<2`), `tavily-python` for web search, FastAPI/Starlette (existing), OpenAI function-calling (existing), pytest + FastAPI `TestClient`.

This is Plan 3 of the phased v1 work (Plan 1 backend foundation and Plan 2 agentic chat are merged). It produces working software: agentic chat that can read the live car and the web. The Vue SPA is Plan 4.

## Key decisions baked into this plan

- **web_search backend = Tavily** (`tavily-python`). Chosen over Brave: one synchronous `client.search(..., include_answer=True)` returns an LLM-ready `answer` plus clean per-result snippets — no SERP post-processing — and it has a no-card 1,000-credit/month free tier. It sits behind a thin executor so swapping providers later is a one-function change. (Resolves the spec's deferred "Tavily/Brave — pinned in the Phase 1 plan.")
- **Async→sync bridge = dedicated event-loop daemon thread** owning the `ClientSession` for the process lifetime; sync callers marshal via `asyncio.run_coroutine_threadsafe`. This is the only robust way to keep one warm session: `anyio`/`stdio_client` lifecycle must open and close on one loop/task, and the orchestrator + SSE body are synchronous (Starlette runs the stream generator in a threadpool).
- **Destructive-tool filtering** uses MCP `annotations.destructiveHint` (the spec's D6). `obd-mcp` flags exactly one: `clear_dtcs`. In addition, a configurable **name denylist** (`OBD_TOOL_DENYLIST`, default `ping,record_session`) drops the health-probe (`ping`) and the long-running sampling tool (`record_session`, up to 600 s — a Phase 2/telemetry concern, not request/response Q&A) from the advertised set.
- **`OBD_MCP_ENABLED` defaults to `false`.** The host needs the separate `obd-mcp` repo present and (for live reads) a scanner/simulator; defaulting off keeps the full test suite subprocess-free and unchanged, and matches the spec's first-class "degrades gracefully" state. The local smoke test enables it.
- **`GET /api/scanner/status`** reports `available` (the `obd-mcp` server connected and listed tools) and `scanner_reachable` (a bounded live `get_vehicle_info` probe succeeded). Phase 2 replaces this global badge with per-vehicle status.

## Global Constraints

- Python ≥ 3.11; manage dependencies with `uv` (`uv add …`, run via `uv run …`).
- All HTTP routes are prefixed `/api`. The chat stream stays `text/event-stream` (SSE), one event per `data: <json>\n\n` line.
- The orchestrator, provider, OpenAI client, and the OBD host's public surface are **synchronous**. The SSE endpoint streams a sync generator via `StreamingResponse` — do not introduce an async wrapper around blocking I/O. All MCP async work is confined to the host's private event-loop thread.
- Pin the MCP SDK to the v1 API: `mcp>=1.28,<2`. Read MCP model fields with v1 **camelCase** attribute names (`tool.inputSchema`, `result.isError`, `result.structuredContent`). Keep those reads centralized in `app/agent/mcp_host.py`.
- Every agent tool is **read-only**: filter out any tool with `annotations.destructiveHint` (this removes `clear_dtcs` and all elicitation plumbing), plus the configured name denylist. The host must also refuse to `call()` any name it did not advertise (defense in depth).
- Tests never hit the network and never require a scanner. OpenAI, embeddings, the OBD host, and the Tavily client are faked/mocked. The single subprocess-spawning test (Task 3) launches a tiny in-repo FastMCP stub via `sys.executable` — no `obd-mcp`, no `uv`, no hardware.
- Run the full suite with `uv run pytest tests/ -v`. The existing CLI and all 95 prior tests must stay green. With `OBD_MCP_ENABLED=false` (default) and no `TAVILY_API_KEY`, the new tool families are dark and existing behavior is byte-for-byte unchanged.
- Commit messages plain and conventional-commit style; no AI/Claude attribution anywhere in tracked content.

---

### Task 1: Dependencies and configuration

**Files:**
- Modify: `pyproject.toml` (dependencies — via `uv add`)
- Modify: `app/config.py`
- Modify: `.env.example`
- Test: `tests/test_config_phase3.py` (create)

**Interfaces:**
- Produces: `Settings` fields — `obd_mcp_enabled: bool`, `obd_mcp_dir: str`, `obd_port: str`, `obd_tool_denylist: str`, `mcp_call_timeout_s: float`, `mcp_start_timeout_s: float`, `web_search_enabled: bool`, `tavily_api_key: str`, `web_search_max_results: int`.

- [ ] **Step 1: Add runtime dependencies**

Run:
```bash
uv add "mcp>=1.28,<2" tavily-python
```
Expected: `pyproject.toml` `dependencies` gains `mcp` and `tavily-python`; `uv.lock` updates; no errors.

- [ ] **Step 2: Write the failing config test**

Create `tests/test_config_phase3.py`:
```python
from app.config import Settings


def test_phase3_settings_defaults():
    s = Settings(_env_file=None)
    assert s.obd_mcp_enabled is False
    assert s.obd_mcp_dir == ""
    assert s.obd_port == "socket://localhost:35000"
    assert s.obd_tool_denylist == "ping,record_session"
    assert s.mcp_call_timeout_s == 30.0
    assert s.mcp_start_timeout_s == 20.0
    assert s.web_search_enabled is True
    assert s.tavily_api_key == ""
    assert s.web_search_max_results == 5
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_config_phase3.py -v`
Expected: FAIL — `AttributeError` on the missing fields.

- [ ] **Step 4: Add the fields to `Settings`**

In `app/config.py`, add inside `Settings` after `max_upload_bytes` (before `model_config`):
```python
    obd_mcp_enabled: bool = False
    obd_mcp_dir: str = ""
    obd_port: str = "socket://localhost:35000"
    obd_tool_denylist: str = "ping,record_session"
    mcp_call_timeout_s: float = 30.0
    mcp_start_timeout_s: float = 20.0
    web_search_enabled: bool = True
    tavily_api_key: str = ""
    web_search_max_results: int = 5
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_config_phase3.py -v`
Expected: PASS.

- [ ] **Step 6: Document the new env vars**

Append to `.env.example`:
```bash
# Phase 3 — live OBD tools (obd-mcp) and web search
OBD_MCP_ENABLED=false
OBD_MCP_DIR=/home/mark/repos/OBD-II-MCP-Server
OBD_PORT=socket://localhost:35000
OBD_TOOL_DENYLIST=ping,record_session
TAVILY_API_KEY=
WEB_SEARCH_ENABLED=true
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/config.py .env.example tests/test_config_phase3.py
git commit -m "feat(agent): add MCP/Tavily deps and OBD + web-search config"
```

---

### Task 2: MCP → OpenAI schema translation and tool filtering (pure functions)

**Files:**
- Create: `app/agent/mcp_host.py` (helper functions only in this task; the `ObdMcpHost` class is added in Task 3)
- Test: `tests/test_agent/test_mcp_schema.py` (create)

**Interfaces:**
- Produces:
  - `sanitize_schema(schema: dict | None) -> dict` — normalizes a tool input schema to a valid OpenAI `parameters` object.
  - `is_destructive(tool) -> bool` — reads `tool.annotations.destructiveHint` defensively (annotations and the field may be `None`).
  - `mcp_tool_to_openai(tool) -> dict` — translates an MCP `Tool` (duck-typed: `.name`, `.description`, `.inputSchema`) to `{"type": "function", "function": {name, description, parameters}}`.
  - `select_openai_tools(tools: list, denylist: set[str]) -> list[dict]` — maps non-destructive, non-denylisted tools through `mcp_tool_to_openai`.

These take duck-typed objects (real `mcp.types.Tool` at runtime; `SimpleNamespace` in tests) so they need no live MCP session.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent/test_mcp_schema.py`:
```python
from types import SimpleNamespace

from app.agent.mcp_host import (
    is_destructive,
    mcp_tool_to_openai,
    sanitize_schema,
    select_openai_tools,
)


def _tool(name, *, schema=None, destructive=None, desc="d"):
    annotations = None if destructive is None else SimpleNamespace(destructiveHint=destructive)
    return SimpleNamespace(
        name=name,
        description=desc,
        inputSchema=schema if schema is not None else {"type": "object", "properties": {}},
        annotations=annotations,
    )


def test_sanitize_schema_normalizes_empty():
    assert sanitize_schema(None) == {"type": "object", "properties": {}}
    assert sanitize_schema({}) == {"type": "object", "properties": {}}


def test_sanitize_schema_passes_through_valid():
    schema = {"type": "object", "properties": {"pids": {"type": "array"}}, "required": ["pids"]}
    assert sanitize_schema(schema) == schema


def test_is_destructive_reads_annotation_defensively():
    assert is_destructive(_tool("clear_dtcs", destructive=True)) is True
    assert is_destructive(_tool("read_dtcs", destructive=False)) is False
    assert is_destructive(_tool("ping", destructive=None)) is False  # annotations is None


def test_mcp_tool_to_openai_shape():
    tool = _tool("read_dtcs", schema={"type": "object", "properties": {"scope": {"type": "string"}}})
    out = mcp_tool_to_openai(tool)
    assert out["type"] == "function"
    assert out["function"]["name"] == "read_dtcs"
    assert out["function"]["description"] == "d"
    assert out["function"]["parameters"]["properties"] == {"scope": {"type": "string"}}


def test_select_openai_tools_filters_destructive_and_denylist():
    tools = [
        _tool("read_dtcs", destructive=False),
        _tool("clear_dtcs", destructive=True),
        _tool("ping", destructive=None),
    ]
    selected = select_openai_tools(tools, denylist={"ping"})
    names = [t["function"]["name"] for t in selected]
    assert names == ["read_dtcs"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent/test_mcp_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: app.agent.mcp_host`.

- [ ] **Step 3: Write the helpers**

Create `app/agent/mcp_host.py`:
```python
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_schema(schema: dict | None) -> dict:
    if not schema or not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out = dict(schema)
    out.setdefault("type", "object")
    if out["type"] == "object":
        out.setdefault("properties", {})
    return out


def is_destructive(tool: Any) -> bool:
    annotations = getattr(tool, "annotations", None)
    return bool(getattr(annotations, "destructiveHint", False))


def mcp_tool_to_openai(tool: Any) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": getattr(tool, "description", "") or "",
            "parameters": sanitize_schema(getattr(tool, "inputSchema", None)),
        },
    }


def select_openai_tools(tools: list, denylist: set[str]) -> list[dict]:
    return [
        mcp_tool_to_openai(tool)
        for tool in tools
        if not is_destructive(tool) and tool.name not in denylist
    ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent/test_mcp_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/mcp_host.py tests/test_agent/test_mcp_schema.py
git commit -m "feat(agent): MCP tool schema translation and read-only filtering"
```

---

### Task 3: ObdMcpHost — long-lived stdio session with a sync surface

**Files:**
- Modify: `app/agent/mcp_host.py` (append `result_to_text`, `ObdMcpHost`, `build_obd_host`)
- Create: `tests/fixtures/__init__.py` (empty), `tests/fixtures/stub_mcp_server.py`
- Test: `tests/test_agent/test_mcp_host.py` (create)

**Interfaces:**
- Consumes: `select_openai_tools` (Task 2), `Settings` (Task 1), the `mcp` SDK.
- Produces:
  - `result_to_text(result) -> str` — extracts plain text from a `CallToolResult` (concatenated `TextContent`, falling back to `json.dumps(structuredContent)`; prefixes `[tool error]` when `isError`).
  - `ObdMcpHost(command, args, env=None, denylist=None, call_timeout=30.0, start_timeout=20.0)` with sync methods: `start() -> bool`, `stop() -> None`, `available: bool` (property), `openai_tools() -> list[dict]`, `handles(name: str) -> bool`, `call(name: str, args: dict) -> str`.
  - `build_obd_host(settings: Settings) -> ObdMcpHost` — constructs the host to spawn `uv --directory <obd_mcp_dir> run obd-mcp` with `OBD_PORT` in the child env and the parsed denylist.

- [ ] **Step 1: Write the in-repo stub MCP server**

Create `tests/fixtures/__init__.py` (empty).

Create `tests/fixtures/stub_mcp_server.py`:
```python
"""A minimal FastMCP server used by host integration tests. No hardware, no network."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("stub")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    return f"echo:{text}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def wipe() -> str:
    return "wiped"


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Write the failing host tests**

Create `tests/test_agent/test_mcp_host.py`:
```python
import sys
from pathlib import Path

import pytest

from app.agent.mcp_host import ObdMcpHost

STUB = str(Path(__file__).resolve().parents[1] / "fixtures" / "stub_mcp_server.py")


def test_start_fails_for_missing_command_and_degrades():
    host = ObdMcpHost(command="/nonexistent-binary-xyz", args=[], start_timeout=5.0)
    try:
        assert host.start() is False
        assert host.available is False
        assert host.openai_tools() == []
        assert host.handles("read_dtcs") is False
        assert host.call("read_dtcs", {}).startswith("[obd unavailable]")
    finally:
        host.stop()


def test_connects_lists_filtered_tools_and_calls():
    host = ObdMcpHost(command=sys.executable, args=[STUB], start_timeout=20.0)
    assert host.start() is True
    try:
        names = [t["function"]["name"] for t in host.openai_tools()]
        assert "echo" in names          # read-only tool advertised
        assert "wipe" not in names       # destructive tool filtered out
        assert host.handles("echo") is True
        assert host.handles("wipe") is False
        assert "echo:hi" in host.call("echo", {"text": "hi"})
        # The host refuses a name it did not advertise, without calling the server.
        assert host.call("wipe", {}).startswith("[obd error]")
    finally:
        host.stop()


def test_denylist_drops_named_tool():
    host = ObdMcpHost(command=sys.executable, args=[STUB], denylist={"echo"}, start_timeout=20.0)
    assert host.start() is True
    try:
        assert host.openai_tools() == []  # echo denylisted, wipe destructive
    finally:
        host.stop()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent/test_mcp_host.py -v`
Expected: FAIL — `ImportError: cannot import name 'ObdMcpHost'`.

- [ ] **Step 4: Append the host implementation**

Append to `app/agent/mcp_host.py` (after `select_openai_tools`):
```python
import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from app.config import Settings


def result_to_text(result: types.CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        elif isinstance(block, types.EmbeddedResource):
            resource = block.resource
            if isinstance(resource, types.TextResourceContents):
                parts.append(resource.text)
    text = "\n".join(part for part in parts if part)
    if not text and result.structuredContent is not None:
        text = json.dumps(result.structuredContent)
    if result.isError:
        text = f"[tool error] {text}" if text else "[tool error] (no detail)"
    return text


class ObdMcpHost:
    """Owns a long-lived MCP stdio session on a private event-loop thread and exposes
    a synchronous surface to the (synchronous) orchestrator and SSE generator."""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        denylist: set[str] | None = None,
        call_timeout: float = 30.0,
        start_timeout: float = 20.0,
    ) -> None:
        merged_env = {**os.environ, **env} if env else None
        self._params = StdioServerParameters(command=command, args=list(args), env=merged_env)
        self._denylist = set(denylist or ())
        self._call_timeout = call_timeout
        self._start_timeout = start_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._openai_tools: list[dict] = []
        self._allowed: set[str] = set()
        self._available = False
        self._ready = threading.Event()
        self._start_error: BaseException | None = None

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run_loop, name="obd-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(self._start_timeout + 5):
            logger.error("ObdMcpHost: startup timed out")
            return False
        if self._start_error is not None:
            logger.warning("ObdMcpHost unavailable: %s", self._start_error)
            return False
        self._available = True
        return True

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect())
            if self._start_error is None:
                self._loop.run_forever()
        finally:
            try:
                if self._stack is not None:
                    self._loop.run_until_complete(self._stack.aclose())
            except Exception:
                logger.exception("ObdMcpHost: error during shutdown")
            finally:
                self._loop.close()

    async def _connect(self) -> None:
        try:
            self._stack = AsyncExitStack()
            read, write = await asyncio.wait_for(
                self._stack.enter_async_context(stdio_client(self._params)),
                self._start_timeout,
            )
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(self._session.initialize(), self._start_timeout)
            tools = (await self._session.list_tools()).tools
            self._openai_tools = select_openai_tools(tools, self._denylist)
            self._allowed = {t["function"]["name"] for t in self._openai_tools}
        except BaseException as exc:  # missing binary, crash, bad protocol, timeout
            self._start_error = exc
            try:
                if self._stack is not None:
                    await self._stack.aclose()
            except Exception:
                pass
            self._session = None
            self._stack = None
        finally:
            self._ready.set()

    @property
    def available(self) -> bool:
        return self._available and self._session is not None

    def openai_tools(self) -> list[dict]:
        return list(self._openai_tools) if self.available else []

    def handles(self, name: str) -> bool:
        return self.available and name in self._allowed

    def call(self, name: str, args: dict) -> str:
        if not self.available:
            return "[obd unavailable] The OBD tool server is not running."
        if name not in self._allowed:
            return f"[obd error] Tool '{name}' is not available."
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(self._call_async(name, args or {}), self._loop)
        try:
            return future.result(timeout=self._call_timeout)
        except Exception as exc:
            logger.exception("OBD tool %s failed", name)
            return f"[tool error] {name}: {exc}"

    async def _call_async(self, name: str, args: dict) -> str:
        assert self._session is not None
        result = await self._session.call_tool(name, args)
        return result_to_text(result)

    def stop(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._available = False


def build_obd_host(settings: Settings) -> ObdMcpHost:
    denylist = {name.strip() for name in settings.obd_tool_denylist.split(",") if name.strip()}
    return ObdMcpHost(
        command="uv",
        args=["--directory", settings.obd_mcp_dir, "run", "obd-mcp"],
        env={"OBD_PORT": settings.obd_port},
        denylist=denylist,
        call_timeout=settings.mcp_call_timeout_s,
        start_timeout=settings.mcp_start_timeout_s,
    )
```
(The `import` lines added here sit mid-file, which works in Python but is non-idiomatic. After the tests pass in Step 5, hoist the new `import asyncio/json/os/threading`, `from contextlib import AsyncExitStack`, the two `mcp` imports, and `from app.config import Settings` up to the top of the module beside the existing imports, then re-run the suite to confirm still green. Keep this hoist in the same commit.)

- [ ] **Step 5: Run the host tests to verify they pass**

Run: `uv run pytest tests/test_agent/test_mcp_host.py -v`
Expected: PASS (3 tests). The degradation test is instant; the two stub tests each spawn `sys.executable` running the FastMCP stub over stdio (~1 s) and tear it down via `stop()`.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS — nothing else touches the host.

- [ ] **Step 7: Commit**

```bash
git add app/agent/mcp_host.py tests/fixtures tests/test_agent/test_mcp_host.py
git commit -m "feat(agent): ObdMcpHost stdio session with sync surface and graceful degradation"
```

---

### Task 4: web_search tool (Tavily)

**Files:**
- Modify: `app/agent/tools.py` (add `WEB_SEARCH_TOOL`, `execute_web_search`)
- Test: `tests/test_agent/test_web_search.py` (create)

**Interfaces:**
- Consumes: a Tavily-like client (duck-typed: `.search(query, include_answer, search_depth, max_results) -> dict`). The real client is constructed in Task 6's factory; here it is injected/mocked.
- Produces:
  - `WEB_SEARCH_TOOL: dict` — an OpenAI function-tool schema, name `web_search`, required string `query`.
  - `execute_web_search(client, query: str, max_results: int = 5) -> dict` returning `{"sources": [], "model_text": str}` — the same `{sources, model_text}` shape every tool executor returns. `sources` is empty by design (web citations are woven into `model_text` as numbered URLs, keeping `sources_json` manuals-only for Plan 4's filename/page rendering).

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent/test_web_search.py`:
```python
from unittest.mock import MagicMock

from app.agent.tools import WEB_SEARCH_TOOL, execute_web_search


def test_web_search_tool_schema():
    assert WEB_SEARCH_TOOL["type"] == "function"
    fn = WEB_SEARCH_TOOL["function"]
    assert fn["name"] == "web_search"
    assert "query" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["query"]


def test_execute_web_search_formats_answer_and_results():
    client = MagicMock()
    client.search.return_value = {
        "answer": "Torque is 40 Nm.",
        "results": [
            {"title": "Forum thread", "url": "http://example.com/a", "content": "snippet text"}
        ],
    }

    result = execute_web_search(client, "brake torque", max_results=3)

    client.search.assert_called_once_with(
        query="brake torque", include_answer=True, search_depth="basic", max_results=3
    )
    assert result["sources"] == []
    assert "Torque is 40 Nm." in result["model_text"]
    assert "http://example.com/a" in result["model_text"]
    assert "snippet text" in result["model_text"]


def test_execute_web_search_empty():
    client = MagicMock()
    client.search.return_value = {"answer": None, "results": []}
    result = execute_web_search(client, "x")
    assert result["sources"] == []
    assert "No relevant web results" in result["model_text"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent/test_web_search.py -v`
Expected: FAIL — `ImportError: cannot import name 'WEB_SEARCH_TOOL'`.

- [ ] **Step 3: Write the implementation**

Append to `app/agent/tools.py`:
```python
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for information not in the uploaded manuals — recalls, "
            "technical service bulletins, common failure patterns, part numbers, or general "
            "procedures. Use this only when search_manuals does not cover the question. Returns a "
            "short answer plus source snippets with their URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query.",
                }
            },
            "required": ["query"],
        },
    },
}


def execute_web_search(client, query: str, max_results: int = 5) -> dict:
    response = client.search(
        query=query,
        include_answer=True,
        search_depth="basic",
        max_results=max_results,
    )
    answer = response.get("answer")
    results = response.get("results", [])
    lines: list[str] = []
    if answer:
        lines.append(f"Answer: {answer}")
    for i, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        lines.append(f"[{i}] {title} ({url})\n{content}")
    model_text = "\n\n".join(lines) if lines else "No relevant web results found."
    return {"sources": [], "model_text": model_text}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_agent/test_web_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools.py tests/test_agent/test_web_search.py
git commit -m "feat(agent): web_search tool backed by Tavily"
```

---

### Task 5: Orchestrator integration (OBD tools + web_search in the loop)

**Files:**
- Modify: `app/agent/orchestrator.py`
- Test: `tests/test_agent/test_orchestrator.py` (extend)

**Interfaces:**
- Consumes: `ObdMcpHost` surface (`available`, `openai_tools()`, `handles()`, `call()`) from Task 3; `WEB_SEARCH_TOOL`/`execute_web_search` from Task 4; existing `SEARCH_MANUALS_TOOL`/`execute_search_manuals`.
- Produces: `AgentOrchestrator.__init__` gains three keyword params with defaults — `obd_host=None`, `web_search_client=None`, `web_search_max_results=5`. The tool list and `_execute` dispatch extend to OBD + web. Event types, persistence, and the manuals-only path are unchanged when the new params default.

- [ ] **Step 1: Write the failing tests**

First, **extend the existing `_orchestrator` helper** in `tests/test_agent/test_orchestrator.py` to thread the two new params through (the prior tests call it positionally with defaults, so they are unaffected). Replace its signature and `return`:
```python
def _orchestrator(db_session, provider, max_iters=6, obd_host=None, web_search_client=None):
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
        max_iters=max_iters,
        obd_host=obd_host,
        web_search_client=web_search_client,
    )
```

Then **append** the new helper classes and tests to the same file:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent/test_orchestrator.py -v`
Expected: FAIL — `AgentOrchestrator.__init__` got an unexpected keyword argument `obd_host`.

- [ ] **Step 3: Extend the orchestrator**

In `app/agent/orchestrator.py`:

(a) Update the import on line 7:
```python
from app.agent.tools import (
    SEARCH_MANUALS_TOOL,
    WEB_SEARCH_TOOL,
    execute_search_manuals,
    execute_web_search,
)
```

(b) Replace the `SYSTEM_PROMPT` (lines 14–21) with:
```python
SYSTEM_PROMPT = (
    "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance. "
    "The vehicle is: {vehicle}. "
    "You have tools: search_manuals (look up specifications, torque values, fluid types, and "
    "procedures in the uploaded service manuals — prefer this for anything the manuals cover); "
    "read-only OBD tools (read live data, trouble codes (DTCs), freeze frames, readiness monitors, "
    "and vehicle info directly from the connected car); and web_search (the public web, for recalls, "
    "bulletins, and information not in the manuals — use only when the manuals do not cover it). "
    "Ground factual answers in the manuals or live readings; never invent specs or codes. When a "
    "diagnostic code or reading needs interpretation, look it up in the manuals. If a needed tool is "
    "unavailable (for example, no scanner is connected), say so plainly. Keep answers concise and "
    "mechanic-friendly, and cite the source filename and page for any specification you quote."
)
```

(c) Replace the `__init__` (lines 25–43) with:
```python
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
        obd_host=None,
        web_search_client=None,
        web_search_max_results: int = 5,
    ) -> None:
        self._chat_repo = chat_repo
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo
        self._doc_repo = doc_repo
        self._retrieval = retrieval
        self._provider = provider
        self._recent_limit = recent_messages_limit
        self._max_iters = max_iters
        self._obd_host = obd_host
        self._web_search_client = web_search_client
        self._web_search_max_results = web_search_max_results
```

(d) Replace the tool-list line (currently line 68, `tools = [SEARCH_MANUALS_TOOL]`) with:
```python
        tools = [SEARCH_MANUALS_TOOL]
        if self._web_search_client is not None:
            tools.append(WEB_SEARCH_TOOL)
        if self._obd_host is not None and self._obd_host.available:
            tools.extend(self._obd_host.openai_tools())
```

(e) Replace the source-collection branch (currently lines 99–100):
```python
                    if tc.name == "search_manuals":
                        sources.extend(result["sources"])
```
with:
```python
                    sources.extend(result.get("sources", []))
```

(f) Replace `_execute` (currently lines 123–128) with:
```python
    def _execute(self, tc: ToolCall, vehicle_id: int) -> dict:
        if tc.name == "search_manuals":
            return execute_search_manuals(
                self._retrieval, self._doc_repo, vehicle_id, tc.arguments.get("query", "")
            )
        if tc.name == "web_search" and self._web_search_client is not None:
            return execute_web_search(
                self._web_search_client,
                tc.arguments.get("query", ""),
                self._web_search_max_results,
            )
        if self._obd_host is not None and self._obd_host.handles(tc.name):
            return {"sources": [], "model_text": self._obd_host.call(tc.name, tc.arguments)}
        return {"sources": [], "model_text": f"Unknown tool: {tc.name}"}
```

- [ ] **Step 4: Run the agent tests to verify they pass**

Run: `uv run pytest tests/test_agent/ -v`
Expected: PASS — the three new tests plus all prior orchestrator/provider/tools tests (the prior tests construct the orchestrator without the new params, so the manuals-only path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/agent/orchestrator.py tests/test_agent/test_orchestrator.py
git commit -m "feat(agent): dispatch OBD and web_search tools in the orchestrator loop"
```

---

### Task 6: Factory + lifespan + chat wiring + scanner status endpoint

**Files:**
- Modify: `app/services/factories.py` (extend `make_chat_orchestrator`)
- Modify: `app/api/main.py` (lifespan starts/stops the host; include scanner router; logging)
- Modify: `app/api/routers/chat.py` (pass `obd_host` from `app.state`)
- Create: `app/api/routers/scanner.py`
- Modify: `tests/test_api/test_chat.py` (update the one monkeypatch lambda for the new factory signature)
- Test: `tests/test_api/test_scanner.py` (create)

**Interfaces:**
- Consumes: `build_obd_host`/`ObdMcpHost` (Task 3), extended `AgentOrchestrator` (Task 5), `Settings`, existing repositories and `get_session`.
- Produces:
  - `make_chat_orchestrator(session, settings, obd_host=None) -> AgentOrchestrator` — builds a Tavily client when `settings.web_search_enabled and settings.tavily_api_key`, and threads `obd_host` through.
  - FastAPI lifespan: when `settings.obd_mcp_enabled`, build + `start()` the host and store it on `app.state.obd_host`; `stop()` it on shutdown. `app.state.obd_host` is always set (to `None` when disabled).
  - Route `GET /api/scanner/status` → `{"available": bool, "scanner_reachable": bool, "detail": str}`.

- [ ] **Step 1: Write the failing scanner tests**

Create `tests/test_api/test_scanner.py`:
```python
def test_scanner_status_no_host(api_client):
    r = api_client.get("/api/scanner/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["scanner_reachable"] is False


def test_scanner_status_reachable(api_client):
    class FakeHost:
        available = True

        def call(self, name, args):
            return '{"vin": "WAUZZZ", "protocol": "ISO 15765-4"}'

    api_client.app.state.obd_host = FakeHost()
    body = api_client.get("/api/scanner/status").json()
    assert body["available"] is True
    assert body["scanner_reachable"] is True


def test_scanner_status_server_up_but_scanner_unreachable(api_client):
    class FakeHost:
        available = True

        def call(self, name, args):
            return "[tool error] [UNABLE_TO_CONNECT] adapter not reachable at socket://localhost:35000"

    api_client.app.state.obd_host = FakeHost()
    body = api_client.get("/api/scanner/status").json()
    assert body["available"] is True
    assert body["scanner_reachable"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_scanner.py -v`
Expected: FAIL — `/api/scanner/status` returns 404 (route not defined).

- [ ] **Step 3: Extend the factory**

In `app/services/factories.py`, replace `make_chat_orchestrator` (lines 35–54) with:
```python
def make_chat_orchestrator(
    session: Session, settings: Settings, obd_host=None
) -> AgentOrchestrator:
    retrieval = RetrievalService(
        ChunkRepository(session),
        make_embedding_service(settings),
        settings.top_k_chunks,
    )
    provider = OpenAIProvider(
        api_key=settings.openai_api_key or None,
        model=settings.openai_chat_model,
    )
    web_search_client = None
    if settings.web_search_enabled and settings.tavily_api_key:
        from tavily import TavilyClient

        web_search_client = TavilyClient(api_key=settings.tavily_api_key)
    return AgentOrchestrator(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval=retrieval,
        provider=provider,
        recent_messages_limit=settings.recent_messages,
        max_iters=settings.max_agent_iters,
        obd_host=obd_host,
        web_search_client=web_search_client,
        web_search_max_results=settings.web_search_max_results,
    )
```
(The `tavily` import is local to the branch so it never runs in tests that lack a key — preserving the network-free test guarantee.)

- [ ] **Step 4: Pass the host from the chat router**

In `app/api/routers/chat.py`, replace the orchestrator construction line (line 36):
```python
            orchestrator = make_chat_orchestrator(session, settings)
```
with:
```python
            obd_host = getattr(request.app.state, "obd_host", None)
            orchestrator = make_chat_orchestrator(session, settings, obd_host=obd_host)
```
(`request` is already a parameter of `send_message`.)

- [ ] **Step 5: Create the scanner router**

Create `app/api/routers/scanner.py`:
```python
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["scanner"])


@router.get("/scanner/status")
def scanner_status(request: Request) -> dict:
    host = getattr(request.app.state, "obd_host", None)
    if host is None or not host.available:
        return {
            "available": False,
            "scanner_reachable": False,
            "detail": "OBD tool server not running.",
        }
    probe = host.call("get_vehicle_info", {})
    reachable = not probe.lstrip().startswith("[")  # error sentinels start with "["
    detail = "Scanner connected." if reachable else "OBD server up; scanner not reachable."
    return {"available": True, "scanner_reachable": reachable, "detail": detail}
```

- [ ] **Step 6: Wire lifespan + router into the app**

In `app/api/main.py`:

(a) Add imports near the top (after the existing imports):
```python
import logging

from app.agent.mcp_host import build_obd_host
from app.api.routers import vehicles, jobs, documents, chat, scanner

logger = logging.getLogger(__name__)
```
(Replace the existing `from app.api.routers import vehicles, jobs, documents, chat` line — do not duplicate it.)

(b) Replace the `lifespan` (lines 22–28) with:
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not getattr(app.state, "session_factory", None):
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        configure_db(app, f"sqlite:///{db_path}")

    app.state.obd_host = None
    if settings.obd_mcp_enabled:
        host = build_obd_host(settings)
        if not host.start():
            logger.warning("OBD MCP host failed to start; chat will run without OBD tools")
        app.state.obd_host = host

    try:
        yield
    finally:
        host = getattr(app.state, "obd_host", None)
        if host is not None:
            host.stop()
```

(c) In `create_app`, add the scanner router beside the others:
```python
    app.include_router(vehicles.router)
    app.include_router(jobs.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(scanner.router)
```

- [ ] **Step 7: Update the existing chat test for the new factory signature**

In `tests/test_api/test_chat.py`, the `test_chat_error_event_on_orchestrator_failure` test monkeypatches the factory with a two-arg lambda. The router now calls it with `obd_host=`. Update that line:
```python
    monkeypatch.setattr(
        "app.api.routers.chat.make_chat_orchestrator",
        lambda session, settings, obd_host=None: _Boom(),
    )
```

- [ ] **Step 8: Run the scanner + chat tests**

Run: `uv run pytest tests/test_api/test_scanner.py tests/test_api/test_chat.py -v`
Expected: PASS. (`test_scanner_status_no_host` exercises the disabled default: lifespan set `app.state.obd_host = None`; the other two inject a fake host onto `app.state` after the client is created.)

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS — all prior tests plus the new ones, pristine. With `OBD_MCP_ENABLED=false` and no `TAVILY_API_KEY`, no test spawns `obd-mcp` or constructs a Tavily client.

- [ ] **Step 10: Commit**

```bash
git add app/services/factories.py app/api/main.py app/api/routers/chat.py app/api/routers/scanner.py tests/test_api/test_scanner.py tests/test_api/test_chat.py
git commit -m "feat(api): wire OBD host + web search into chat and add scanner status"
```

---

## Manual smoke test (after all tasks)

This is the only step that needs the real `obd-mcp` repo and a scanner or simulator. The default `socket://localhost:35000` points at an Ircama `elm327-emulator` if you have one running; otherwise OBD tool *calls* return `[UNABLE_TO_CONNECT]` while everything else works.

In `.env`:
```bash
OPENAI_API_KEY=sk-...
OBD_MCP_ENABLED=true
OBD_MCP_DIR=/home/mark/repos/OBD-II-MCP-Server
OBD_PORT=socket://localhost:35000
TAVILY_API_KEY=tvly-...
```

```bash
# (optional) start the simulator in another shell first, e.g. `elm -s car`
uv run mechanic-sidekick-api

# server connected? (no scanner needed for this to report available=true)
curl -s localhost:8000/api/scanner/status

# create a vehicle + job (or reuse), then ask something that exercises a live read:
curl -N -X POST localhost:8000/api/jobs/1/messages \
  -H 'content-type: application/json' \
  -d '{"content":"Read the trouble codes and tell me what P-codes are stored."}'
# expect SSE: token… tool_call(read_dtcs) tool_result … token… done

# a web-search question:
curl -N -X POST localhost:8000/api/jobs/1/messages \
  -H 'content-type: application/json' \
  -d '{"content":"Are there any safety recalls for this vehicle?"}'
# expect a tool_call(web_search) in the stream
```
Verify graceful degradation: set `OBD_MCP_ENABLED=false`, restart, and confirm `/api/scanner/status` reports `available:false` and chat still answers manuals/web questions.

## Self-review

**Spec coverage (design spec §1.2 `app/agent/mcp_client.py`+`tools.py`, §1.3 MCP client/tools, §1.8/§1.9 degradation+safety, §1.11 `/api/scanner/status`, build order items 5–6):**
- MCP host over stdio, list_tools once, keep warm, schema translation, `clear_dtcs` filtered → Tasks 2–3. ✔
- Read-only OBD tools in the agent loop → Task 5. ✔
- `web_search` (provider-agnostic, Tavily pinned) → Tasks 4–5. ✔
- Graceful degradation when `obd-mcp` is down/disabled (manuals+web only; OBD calls return a clear sentinel) → host (Task 3) + tool-list gating (Task 5) + lifespan (Task 6). ✔
- `GET /api/scanner/status` → Task 6. ✔
- Read-only safety / no destructive tool reaches the model (D6) → `is_destructive` filter + host `call()` refusal (Tasks 2–3). ✔
- No schema migration; SSE event contract unchanged → Tasks 5–6 preserve the `{type:...}` events and `chat_message` persistence. ✔
- Out of scope (Plan 4): the Vue SPA, per-vehicle scanner status (Phase 2), persisting the tool trace. Correctly excluded.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test shows assertions. ✔

**Type consistency:**
- Tool executor return shape `{"sources": list[dict], "model_text": str}` is identical across `execute_search_manuals` (existing), `execute_web_search` (Task 4), and the OBD wrap in `_execute` (Task 5). ✔
- `ObdMcpHost` sync surface (`available` property, `openai_tools()`, `handles()`, `call()`) is defined in Task 3 and consumed identically by `_execute`/tool-list (Task 5), `FakeObdHost` (Task 5 tests), and the scanner router's `host.call`/`host.available` (Task 6). ✔
- `select_openai_tools(tools, denylist)`, `is_destructive(tool)`, `mcp_tool_to_openai(tool)`, `sanitize_schema(schema)` signatures match between Task 2 (def) and Task 3 (use). ✔
- `make_chat_orchestrator(session, settings, obd_host=None)` matches between Task 6 def, the chat router call (Task 6), and the updated monkeypatch lambda (Task 6 Step 7). ✔
- `build_obd_host(settings)` matches between Task 3 def and the Task 6 lifespan call. ✔
- New `AgentOrchestrator` params (`obd_host`, `web_search_client`, `web_search_max_results`) match between Task 5 def, the Task 5 test helper, and the Task 6 factory. ✔
- MCP v1 camelCase reads (`inputSchema`, `isError`, `structuredContent`, `annotations.destructiveHint`) are confined to `app/agent/mcp_host.py`. ✔
```
