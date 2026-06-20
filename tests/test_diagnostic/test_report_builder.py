import json

from app.config import Settings
from app.diagnostic.report import Finding, ReportBuilder

S = Settings(_env_file=None)


class FakeProvider:
    def __init__(self, raw):
        self._raw = raw
        self.calls = []

    def stream_turn(self, messages, tools, max_tokens=None):
        self.calls.append(messages)
        from app.agent.provider import ProviderTurn
        yield {"type": "turn", "turn": ProviderTurn(text=self._raw, tool_calls=[])}


def test_build_merges_llm_text_and_derives_status():
    raw = json.dumps({
        "summary": "One lean bank, otherwise healthy.",
        "findings": {
            "fuel": {"interpretation": "Running lean under load.",
                     "recommendation": "Inspect for a vacuum leak."},
            "cooling": {"interpretation": "Thermostat operating normally.",
                        "recommendation": "No action."},
        },
    })
    builder = ReportBuilder(FakeProvider(raw), S)
    diagnoses = [Finding("fuel", "warn", "LTFT +14%",
                         evidence={"sources": [{"filename": "m.pdf", "page": 142}]})]
    good = {"cooling": "Coolant reached 88C and held steady."}
    report = builder.build("2004 Audi A8", good_systems=good, diagnoses=diagnoses)

    assert report.overall_status == "fair"  # one warn
    assert report.summary.startswith("One lean")
    fuel = next(f for f in report.findings if f.system == "fuel")
    assert fuel.recommendation == "Inspect for a vacuum leak."
    cooling = next(f for f in report.findings if f.system == "cooling")
    assert cooling.severity == "good"
    assert cooling.interpretation == "Thermostat operating normally."


def test_build_survives_bad_json():
    builder = ReportBuilder(FakeProvider("not json"), S)
    report = builder.build("v", good_systems={"cooling": "ok"},
                           diagnoses=[Finding("fuel", "fail", "hot")])
    assert report.overall_status == "poor"  # derived from severities regardless
    assert report.summary  # non-empty fallback
    assert {f.system for f in report.findings} == {"cooling", "fuel"}
