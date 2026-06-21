import json

import pytest

from evals.golden import load_golden


def _write(tmp_path, data):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_load_golden_parses_content_based_question(tmp_path):
    path = _write(tmp_path, [
        {"id": "q1", "question": "What is P0420?", "answer_contains": ["P0420"], "type": "exact_token"},
    ])
    items = load_golden(path)
    assert items[0]["answer_contains"] == ["P0420"]


def test_load_golden_parses_page_based_question(tmp_path):
    path = _write(tmp_path, [
        {"id": "q1", "question": "Remove thermostat?", "relevant_pages": [8964], "type": "conceptual"},
    ])
    items = load_golden(path)
    assert items[0]["relevant_pages"] == [8964]


def test_load_golden_rejects_question_with_no_target(tmp_path):
    path = _write(tmp_path, [{"id": "q1", "question": "x", "type": "exact_token"}])
    with pytest.raises(ValueError):
        load_golden(path)


def test_load_golden_accepts_paraphrase_type(tmp_path):
    # paraphrase = the answer is an exact token but the query does NOT contain it (stresses retrieval).
    path = _write(tmp_path, [
        {"id": "q1", "question": "catalyst efficiency fault?", "answer_contains": ["P0420"], "type": "paraphrase"},
    ])
    assert load_golden(path)[0]["type"] == "paraphrase"


def test_load_golden_rejects_unknown_type(tmp_path):
    path = _write(tmp_path, [{"id": "q1", "question": "x", "answer_contains": ["a"], "type": "bogus"}])
    with pytest.raises(ValueError):
        load_golden(path)


def test_repo_golden_set_loads_and_is_substantial():
    # The shipped F-150 golden set must stay valid and cover both question types.
    items = load_golden("evals/golden_questions.json")
    assert len(items) >= 15
    assert any(q["type"] == "exact_token" for q in items)
    assert any(q["type"] == "conceptual" for q in items)
