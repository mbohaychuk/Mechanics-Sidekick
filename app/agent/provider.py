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
    def stream_turn(
        self, messages: list[dict], tools: list[dict], max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> Iterator[dict]:
        """Yield {"type": "token", "text": str} events during content, then
        exactly one terminal {"type": "turn", "turn": ProviderTurn}."""
        ...


class OpenAIProvider:
    def __init__(self, api_key: str | None, model: str, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=api_key, timeout=120.0, max_retries=2)
        self._model = model

    def stream_turn(
        self, messages: list[dict], tools: list[dict], max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> Iterator[dict]:
        kwargs = dict(
            model=self._model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            stream=True,
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        stream = self._client.chat.completions.create(**kwargs)
        text_parts: list[str] = []
        acc: dict[int, dict] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # OpenAI emits content=None on tool-only chunks and content="" on role-header chunks; skip both
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
