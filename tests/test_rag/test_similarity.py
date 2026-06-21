import json
import pytest
from unittest.mock import MagicMock
from app.rag.similarity import cosine_similarity, rank_chunks


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_zero_vector_returns_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_mismatched_dimensions_returns_zero():
    # A heterogeneous corpus (e.g. after an embed-model/provider swap) must degrade, not crash.
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0]) == 0.0


def test_rank_chunks_degrades_on_dimension_mismatch_instead_of_crashing():
    good = MagicMock()
    good.embedding_json = json.dumps([1.0, 0.0])
    stale = MagicMock()
    stale.embedding_json = json.dumps([1.0, 0.0, 0.0])  # wrong dimension (legacy embed model)

    results = rank_chunks(query_vec=[1.0, 0.0], chunks=[good, stale], top_k=5)

    assert len(results) == 2
    assert results[0][0] is good          # the dimension-matching chunk ranks first
    assert results[-1][1] == 0.0          # the stale chunk scores 0.0 rather than crashing


def test_rank_chunks_returns_sorted_descending():
    chunk_a = MagicMock()
    chunk_a.embedding_json = json.dumps([1.0, 0.0, 0.0])
    chunk_b = MagicMock()
    chunk_b.embedding_json = json.dumps([0.0, 1.0, 0.0])
    chunk_c = MagicMock()
    chunk_c.embedding_json = json.dumps([0.9, 0.1, 0.0])

    results = rank_chunks(query_vec=[1.0, 0.0, 0.0], chunks=[chunk_a, chunk_b, chunk_c], top_k=2)

    assert len(results) == 2
    assert results[0][0] is chunk_a
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][0] is chunk_c


def test_rank_chunks_skips_null_embeddings():
    chunk_a = MagicMock()
    chunk_a.embedding_json = json.dumps([1.0, 0.0])
    chunk_b = MagicMock()
    chunk_b.embedding_json = None

    results = rank_chunks(query_vec=[1.0, 0.0], chunks=[chunk_a, chunk_b], top_k=5)
    assert len(results) == 1
    assert results[0][0] is chunk_a


# ── Reciprocal Rank Fusion (hybrid BM25 + cosine) ──────────────────────────────
from types import SimpleNamespace
from app.rag.similarity import rank_fusion


def _c(cid):
    return SimpleNamespace(id=cid, content=f"chunk {cid}")


def test_rank_fusion_reorders_by_fused_score_and_keeps_cosine():
    a, b, c = _c(1), _c(2), _c(3)
    cosine_scored = [(a, 0.9), (b, 0.8), (c, 0.1)]   # cosine ranks: a, b, c
    bm25_ids = [3, 1]                                 # BM25 ranks: c, a (b absent)
    # RRF(k=60): a=1/61+1/62 > c=1/63+1/61 > b=1/62  -> [a, c, b]
    fused = rank_fusion(cosine_scored, bm25_ids, k=60)
    assert [chunk.id for chunk, _ in fused] == [1, 3, 2]
    assert [score for _, score in fused] == [0.9, 0.1, 0.8]  # each chunk keeps its cosine


def test_rank_fusion_pure_cosine_when_bm25_empty():
    a, b = _c(1), _c(2)
    cosine_scored = [(a, 0.9), (b, 0.2)]
    assert rank_fusion(cosine_scored, [], k=60) == [(a, 0.9), (b, 0.2)]
