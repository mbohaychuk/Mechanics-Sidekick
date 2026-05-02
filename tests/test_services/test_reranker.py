# tests/test_services/test_reranker.py
from app.models.document_chunk import DocumentChunk
from app.services.reranker import IdentityReranker, Reranker


def _chunk(content: str) -> DocumentChunk:
    return DocumentChunk(document_id=1, chunk_index=0, content=content)


def test_identity_reranker_preserves_order_and_truncates_to_top_k():
    chunks = [_chunk("a"), _chunk("b"), _chunk("c"), _chunk("d")]
    reranker: Reranker = IdentityReranker()
    out = reranker.rerank(query="anything", candidates=chunks, top_k=2)

    assert [c.content for c, _ in out] == ["a", "b"]
    assert all(score == 1.0 for _, score in out)


def test_identity_reranker_handles_empty_input():
    reranker = IdentityReranker()
    assert reranker.rerank(query="x", candidates=[], top_k=5) == []


def test_bge_reranker_calls_cross_encoder_with_pairs_and_returns_top_k():
    from app.services.reranker import BgeReranker

    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    class FakeCE:
        def __init__(self):
            self.calls = []

        def predict(self, pairs):
            self.calls.append(pairs)
            # Simulate scores: c > a > b
            scoremap = {"a": 0.5, "b": 0.1, "c": 0.9}
            return [scoremap[p[1]] for p in pairs]

    fake = FakeCE()
    reranker = BgeReranker(model_name="fake/model", cross_encoder=fake)
    out = reranker.rerank(query="q", candidates=chunks, top_k=2)

    # Pairs were (query, content) for each candidate.
    assert fake.calls == [[("q", "a"), ("q", "b"), ("q", "c")]]
    # Top-2 by score: c then a.
    assert [c.content for c, _ in out] == ["c", "a"]
    assert out[0][1] == 0.9
    assert out[1][1] == 0.5


def test_bge_reranker_returns_empty_when_no_candidates():
    from app.services.reranker import BgeReranker

    class FakeCE:
        def predict(self, pairs):
            raise AssertionError("should not call predict on empty")

    reranker = BgeReranker(model_name="fake", cross_encoder=FakeCE())
    assert reranker.rerank(query="q", candidates=[], top_k=10) == []
