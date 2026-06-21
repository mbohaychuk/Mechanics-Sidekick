import pytest

from evals.metrics import hit_at_k, reciprocal_rank


def test_hit_at_k_true_when_relevant_within_k():
    assert hit_at_k([False, True, False], k=2) is True


def test_hit_at_k_false_when_relevant_beyond_k():
    assert hit_at_k([False, False, True], k=2) is False


def test_hit_at_k_false_when_none_relevant():
    assert hit_at_k([False, False], k=2) is False


def test_hit_at_k_rejects_nonpositive_k():
    with pytest.raises(ValueError):
        hit_at_k([True], k=0)


def test_reciprocal_rank_uses_first_relevant_position():
    assert reciprocal_rank([False, True, True]) == pytest.approx(0.5)


def test_reciprocal_rank_one_when_first_is_relevant():
    assert reciprocal_rank([True, False]) == pytest.approx(1.0)


def test_reciprocal_rank_zero_when_none_relevant():
    assert reciprocal_rank([False, False, False]) == pytest.approx(0.0)
