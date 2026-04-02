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
