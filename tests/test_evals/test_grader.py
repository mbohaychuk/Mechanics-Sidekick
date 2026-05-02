# tests/test_evals/test_grader.py
from unittest.mock import MagicMock

from app.services.ollama_service import OllamaService
from evals.grader import GraderResult, LlmJudgeGrader, SubstringAnyGrader


def test_substring_any_passes_when_any_substring_present():
    grader = SubstringAnyGrader()
    result = grader.grade(
        answer="The maximum warpage is 0.10 mm.",
        substrings=["0.1 mm", "0.10 mm"],
    )
    assert result.passed is True
    assert "0.10 mm" in result.matched


def test_substring_any_fails_when_no_substring_present():
    grader = SubstringAnyGrader()
    result = grader.grade(
        answer="The torque is 50 Nm.",
        substrings=["129 Nm", "120 Nm"],
    )
    assert result.passed is False
    assert result.matched == []


def test_substring_any_is_case_insensitive():
    grader = SubstringAnyGrader()
    result = grader.grade(
        answer="HEAD BOLT TORQUE IS 129 NM",
        substrings=["129 Nm"],
    )
    assert result.passed is True


def test_substring_any_empty_substrings_treats_as_pass():
    """No expected substrings means any answer passes — used by negative-case entries."""
    grader = SubstringAnyGrader()
    result = grader.grade(answer="anything", substrings=[])
    assert result.passed is True


def test_substring_any_handles_multi_word_substring():
    grader = SubstringAnyGrader()
    result = grader.grade(
        answer="Use a diagonal pattern when tightening to 120 Nm.",
        substrings=["120 Nm", "diagonal"],
    )
    assert result.passed is True
    assert sorted(result.matched) == ["120 Nm", "diagonal"]


def test_llm_judge_passes_when_judge_says_so():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"passed": true, "rationale": "all steps present"}'
    grader = LlmJudgeGrader(ollama, model="m")
    out = grader.grade(
        answer="Step 1, Step 2, Step 3", rubric="Should describe 3 steps", question="how to bleed?"
    )
    assert out.passed is True


def test_llm_judge_fails_closed_on_malformed():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ['nope', 'still nope']
    grader = LlmJudgeGrader(ollama, model="m")
    out = grader.grade(answer="x", rubric="y", question="z")
    assert out.passed is False
    assert "malformed" in out.rationale.lower()
