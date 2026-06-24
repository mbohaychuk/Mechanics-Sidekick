from __future__ import annotations

import json
from typing import Any


class LiveReadError(Exception):
    """The host returned a sentinel string (not JSON) — the adapter call failed."""


def _load(text: str) -> Any:
    # Fast path: the host returned a single JSON value (dict or array).
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # The MCP host serializes a list-returning tool (read_live_data) as one content block per row
    # and joins them with newlines, so the payload is several concatenated JSON objects (NDJSON),
    # not one JSON value. Decode them all. A genuine sentinel ("[tool error] ...") still fails here.
    decoder = json.JSONDecoder()
    items: list = []
    idx, n = 0, len(text)
    try:
        while idx < n:
            while idx < n and text[idx].isspace():
                idx += 1
            if idx >= n:
                break
            obj, idx = decoder.raw_decode(text, idx)
            items.append(obj)
    except json.JSONDecodeError as exc:
        raise LiveReadError(text) from exc
    if not items:
        raise LiveReadError(text)
    return items


def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("result", "results", "readings", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        if data.get("name") or data.get("pid"):  # a bare single reading row
            return [data]
    return []


def parse_live_data(text: str) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for entry in _as_list(_load(text)):
        name = entry.get("name")
        if not name:
            continue
        # obd-mcp rows always carry an "error" key (null on success), so test the VALUE, not presence.
        out[name] = None if entry.get("error") else {"value": entry.get("value"), "unit": entry.get("unit")}
    return out


def parse_supported_pids(text: str) -> list[dict]:
    return [
        {"pid": e.get("pid"), "name": e.get("name"), "description": e.get("description")}
        for e in _as_list(_load(text))
        if e.get("name")
    ]


def parse_vin(text: str) -> str | None:
    data = _load(text)
    if isinstance(data, dict):
        return data.get("vin")
    return None
