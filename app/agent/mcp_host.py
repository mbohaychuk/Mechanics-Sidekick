from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from app.config import Settings

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
        # Intentionally inherit the full parent environment so `uv`/the child can
        # resolve PATH, HOME, and the obd-mcp venv; `env` only layers OBD_PORT on top.
        # obd-mcp is a local, trusted process — revisit this scoping if it ever runs untrusted.
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
        self._lock: asyncio.Lock | None = None

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run_loop, name="obd-mcp", daemon=True)
        self._thread.start()
        if not self._ready.wait(self._start_timeout + 5):
            logger.error("ObdMcpHost: startup timed out")
            return False
        if self._start_error is not None:
            # exc_info logs the full traceback + exception type so a bad obd_mcp_dir / missing uv /
            # protocol error is diagnosable, not just a one-line message.
            logger.warning("ObdMcpHost unavailable", exc_info=self._start_error)
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
            self._lock = asyncio.Lock()
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
        if self._loop is None or self._loop.is_closed():
            return "[obd unavailable] The OBD tool server is not running."
        future = asyncio.run_coroutine_threadsafe(self._call_async(name, args), self._loop)
        try:
            return future.result(timeout=self._call_timeout)
        except Exception as exc:
            logger.exception("OBD tool %s failed", name)
            return f"[tool error] {name}: {exc}"

    async def _call_async(self, name: str, args: dict) -> str:
        assert self._lock is not None
        async with self._lock:
            result = await self._session.call_tool(name, args)
        return result_to_text(result)

    async def call_async(self, name: str, args: dict) -> str:
        if not self.available:
            return "[obd unavailable] The OBD tool server is not running."
        if name not in self._allowed:
            return f"[obd error] Tool '{name}' is not available."
        if self._loop is None or self._loop.is_closed():
            return "[obd unavailable] The OBD tool server is not running."
        future = asyncio.run_coroutine_threadsafe(self._call_async(name, args), self._loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), self._call_timeout)
        except Exception as exc:
            logger.exception("OBD tool %s failed (async)", name)
            return f"[tool error] {name}: {exc}"

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
