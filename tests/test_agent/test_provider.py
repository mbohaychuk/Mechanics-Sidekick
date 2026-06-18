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
