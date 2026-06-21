import sys
import types
from types import SimpleNamespace

from app.services.reranker import FlashRankReranker, NoOpReranker, _enriched_text


def chunk(content, ctx=None, sec=None, page=1):
    return SimpleNamespace(content=content, context_summary=ctx, section_title=sec, page_number=page)


def test_noop_reranker_returns_input_unchanged():
    scored = [(chunk("a"), 0.9), (chunk("b"), 0.5)]
    assert NoOpReranker().rerank("q", scored) is scored


def test_enriched_text_includes_context_and_section():
    text = _enriched_text(chunk("body text", ctx="applies to 5.0L", sec="ENGINE > SPECIFICATIONS"))
    assert "applies to 5.0L" in text
    assert "ENGINE > SPECIFICATIONS" in text
    assert "body text" in text


def test_enriched_text_is_bare_content_when_no_metadata():
    assert _enriched_text(chunk("just body")) == "just body"


def _install_fake_flashrank(monkeypatch, order_fn):
    """Inject a fake `flashrank` module so FlashRankReranker is testable without the real dep/model."""
    class FakeRanker:
        def __init__(self, model_name):
            self.model_name = model_name

        def rerank(self, request):
            return [{"id": p["id"]} for p in order_fn(request.passages)]

    class FakeRerankRequest:
        def __init__(self, query, passages):
            self.query = query
            self.passages = passages

    fake = types.ModuleType("flashrank")
    fake.Ranker = FakeRanker
    fake.RerankRequest = FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake)


def test_flashrank_reorders_by_model_and_preserves_original_tuples(monkeypatch):
    _install_fake_flashrank(monkeypatch, order_fn=lambda passages: list(reversed(passages)))
    reranker = FlashRankReranker("any-model")
    scored = [(chunk("a"), 0.9), (chunk("b"), 0.5), (chunk("c"), 0.1)]

    out = reranker.rerank("q", scored)

    assert [c.content for c, _ in out] == ["c", "b", "a"]      # model order honored
    assert [s for _, s in out] == [0.1, 0.5, 0.9]              # each chunk keeps its ORIGINAL cosine


def test_flashrank_short_circuits_single_candidate(monkeypatch):
    _install_fake_flashrank(monkeypatch, order_fn=lambda passages: passages)
    reranker = FlashRankReranker("any-model")
    scored = [(chunk("only"), 0.7)]
    assert reranker.rerank("q", scored) is scored
