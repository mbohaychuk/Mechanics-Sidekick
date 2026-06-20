from app.config import Settings
from app.diagnostic.commentary import Commentary, CommentaryGenerator, summarize_window
from app.diagnostic.protocol import Step, StepState, StepTarget

S = Settings(_env_file=None)


class FakeProvider:
    """Yields the scripted raw string as a single token then a turn carrying it."""
    def __init__(self, raw):
        self._raw = raw
        self.calls = []

    def stream_turn(self, messages, tools, max_tokens=None, response_format=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "response_format": response_format})
        from app.agent.provider import ProviderTurn
        yield {"type": "token", "text": self._raw}
        yield {"type": "turn", "turn": ProviderTurn(text=self._raw, tool_calls=[])}


def _step():
    return StepState(index=2, total=5,
                     step=Step(id="rev_2500", label="Rev to 2500", instruction="hold 2500",
                               target=StepTarget("RPM", 2300, 2700)),
                     state="active")


def test_summarize_window_downsamples_and_aggregates():
    samples = [{"seq": i, "t": i * 100, "values": {"RPM": {"value": 700 + i, "unit": "rpm"}}}
               for i in range(100)]
    out = summarize_window(samples, ["RPM"], max_points=10)
    assert out["points"] <= 10
    assert out["pids"]["RPM"]["min"] == 700
    assert out["pids"]["RPM"]["max"] == 799
    assert "mean" in out["pids"]["RPM"]


def test_comment_parses_structured_json_and_passes_max_tokens():
    provider = FakeProvider('{"comment": "Idle looks steady.", "adapt": null}')
    gen = CommentaryGenerator(provider, S)
    window = {"points": 3, "pids": {"RPM": {"last": 720, "min": 700, "max": 740, "mean": 720}}}
    c = gen.comment(window, _step(), [], "2004 Audi A8")
    assert isinstance(c, Commentary)
    assert c.comment == "Idle looks steady."
    assert c.adapt is None
    assert provider.calls[0]["max_tokens"] == S.diag_commentary_max_tokens


def test_comment_extracts_adapt_directive():
    raw = '{"comment": "Trim is odd, hold 2000.", "adapt": {"action": "insert", "step": {"pid": "RPM", "low": 1900, "high": 2100}}}'
    gen = CommentaryGenerator(FakeProvider(raw), S)
    c = gen.comment({"points": 0, "pids": {}}, _step(), [], "v")
    assert c.adapt["action"] == "insert" and c.adapt["step"]["pid"] == "RPM"


def test_comment_survives_non_json():
    gen = CommentaryGenerator(FakeProvider("not json at all"), S)
    c = gen.comment({"points": 0, "pids": {}}, None, [], "v")
    assert c.adapt is None
    assert c.comment == "not json at all"
