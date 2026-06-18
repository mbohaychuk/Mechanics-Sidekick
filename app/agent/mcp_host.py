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
