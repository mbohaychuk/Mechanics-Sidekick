from app.agent.provider import OpenAIProvider


class _FakeChunkDelta:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeChunkDelta(content)


class _FakeChunk:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return iter([_FakeChunk("hello")])


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_max_tokens_is_forwarded_when_set():
    client = _FakeClient()
    provider = OpenAIProvider(api_key=None, model="m", client=client)
    list(provider.stream_turn([{"role": "user", "content": "hi"}], [], max_tokens=42))
    assert client.chat.completions.kwargs["max_tokens"] == 42


def test_max_tokens_omitted_when_none():
    client = _FakeClient()
    provider = OpenAIProvider(api_key=None, model="m", client=client)
    list(provider.stream_turn([{"role": "user", "content": "hi"}], []))
    assert "max_tokens" not in client.chat.completions.kwargs
