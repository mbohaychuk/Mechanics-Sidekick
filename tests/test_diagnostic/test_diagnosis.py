from app.config import Settings
from app.diagnostic.anomaly import AnomalyFlag
from app.diagnostic.diagnosis import Diagnoser

S = Settings(_env_file=None)


class FakeRetrieval:
    """retrieve() returns a list of (chunk, score). Diagnoser calls execute_search_manuals,
    which calls retrieval.retrieve and doc_repo.get_by_id."""
    def __init__(self, score):
        self._score = score

    def retrieve(self, vehicle_id, question, mode="auto"):
        chunk = type("C", (), {"document_id": 1, "page_number": 142, "content": "Lean code fix."})()
        return [(chunk, self._score)]


class FakeDocRepo:
    def get_by_id(self, doc_id):
        return type("D", (), {"file_name": "service.pdf"})()


class FakeWeb:
    def __init__(self):
        self.called = False

    def search(self, query, include_answer, search_depth, max_results):
        self.called = True
        return {"answer": "Common lean cause: vacuum leak.", "results": [
            {"title": "Forum", "url": "http://x", "content": "vacuum leak"}]}


def _flag():
    return AnomalyFlag("fuel", "warn", "LONG_FUEL_TRIM_1", "LONG_FUEL_TRIM_1 +14.0% (lean)", 14.0)


def test_high_manual_score_skips_web():
    web = FakeWeb()
    d = Diagnoser(FakeRetrieval(score=0.8), FakeDocRepo(), web, vehicle_id=1, settings=S)
    finding = d.diagnose(_flag(), "2004 Audi A8")
    assert finding.system == "fuel" and finding.severity == "warn"
    assert finding.observation.startswith("LONG_FUEL_TRIM_1")
    assert finding.evidence["sources"][0]["filename"] == "service.pdf"
    assert finding.evidence["readings"][0]["value"] == 14.0
    assert web.called is False
    assert finding.evidence["web_text"] == ""


def test_low_manual_score_triggers_web():
    web = FakeWeb()
    d = Diagnoser(FakeRetrieval(score=0.1), FakeDocRepo(), web, vehicle_id=1, settings=S)
    finding = d.diagnose(_flag(), "2004 Audi A8")
    assert web.called is True
    assert "vacuum leak" in finding.evidence["web_text"]


def test_no_web_client_is_safe():
    d = Diagnoser(FakeRetrieval(score=0.1), FakeDocRepo(), None, vehicle_id=1, settings=S)
    finding = d.diagnose(_flag(), "2004 Audi A8")
    assert finding.evidence["web_text"] == ""
