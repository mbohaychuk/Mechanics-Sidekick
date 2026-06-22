from types import SimpleNamespace

import pytest

from evals.runner import chunk_is_relevant, relevance_flags, run_eval, summarize


def chunk(page, content=""):
    return SimpleNamespace(page_number=page, content=content, section_title="")


def test_chunk_relevant_by_content_substring_case_insensitive():
    assert chunk_is_relevant(chunk(5, "DTC P0420 Catalyst"), ["p0420"], []) is True


def test_chunk_relevant_by_page_fallback_when_content_misses():
    assert chunk_is_relevant(chunk(8525, "no token here"), ["1.25-1.35"], [8525]) is True


def test_chunk_not_relevant_when_neither_content_nor_page_match():
    assert chunk_is_relevant(chunk(7, "unrelated"), ["p0420"], [8525]) is False


def test_relevance_flags_are_per_rank():
    results = [(chunk(1, "misfire P0300 detected"), 0.9), (chunk(2, "unrelated"), 0.8)]
    assert relevance_flags(results, ["P0300"], []) == [True, False]


def test_summarize_overall_and_by_type():
    per_q = [
        {"type": "exact_token", "hit": True, "hit1": True, "reciprocal_rank": 1.0},
        {"type": "exact_token", "hit": False, "hit1": False, "reciprocal_rank": 0.0},
        {"type": "conceptual", "hit": True, "hit1": False, "reciprocal_rank": 0.5},
    ]
    s = summarize(per_q)
    assert s["n"] == 3
    assert s["mrr"] == pytest.approx(0.5)
    assert s["hit_rate"] == pytest.approx(2 / 3)
    assert s["hit_rate_at_1"] == pytest.approx(1 / 3)
    assert s["by_type"]["exact_token"]["n"] == 2
    assert s["by_type"]["exact_token"]["hit_rate"] == pytest.approx(0.5)
    assert s["by_type"]["exact_token"]["hit_rate_at_1"] == pytest.approx(0.5)


class _FakeRetrieval:
    def __init__(self, by_question):
        self._by_question = by_question

    def retrieve(self, vehicle_id, question, mode="auto"):
        return self._by_question[question]


def test_run_eval_scores_content_and_page_questions():
    svc = _FakeRetrieval({
        "P0420?": [(chunk(10, "... P0420 ..."), 0.9), (chunk(11, "x"), 0.8)],   # content hit at rank 1
        "thermostat?": [(chunk(999, "x"), 0.7), (chunk(8964, "steps"), 0.6)],   # page hit at rank 2
    })
    questions = [
        {"id": "q1", "question": "P0420?", "answer_contains": ["P0420"], "type": "exact_token"},
        {"id": "q2", "question": "thermostat?", "relevant_pages": [8964], "type": "conceptual"},
    ]
    report = run_eval(svc, vehicle_id=1, questions=questions, k=5)

    assert report["summary"]["hit_rate"] == pytest.approx(1.0)
    assert report["summary"]["hit_rate_at_1"] == pytest.approx(0.5)  # only q1 is relevant at rank 1
    q1 = next(r for r in report["per_question"] if r["id"] == "q1")
    assert q1["hit"] is True
    assert q1["hit1"] is True
    assert q1["reciprocal_rank"] == pytest.approx(1.0)
    q2 = next(r for r in report["per_question"] if r["id"] == "q2")
    assert q2["hit1"] is False
    assert q2["reciprocal_rank"] == pytest.approx(0.5)
