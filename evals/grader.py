# evals/grader.py
"""Graders for the evaluation harness.

SubstringAnyGrader is deterministic and offline: pass if at least one expected
substring is found in the answer (case-insensitive). Used for fact-lookup
questions where ground truth is a small set of expected strings (torque values,
DTC names, etc.).

LlmJudgeGrader uses a strong model (gemma4:26b) for procedural questions where
the answer is a multi-step procedure that can vary in wording. The judge is
given a rubric (`expected_answer_summary`) and returns pass/fail. Fail-closed
on malformed output.
"""
from dataclasses import dataclass

from app.rag.grader import _parse_json
from app.services.ollama_service import OllamaService


@dataclass
class GraderResult:
    passed: bool
    matched: list[str]
    rationale: str


class SubstringAnyGrader:
    """Pass if at least one expected substring is found, case-insensitive."""

    def grade(self, answer: str, substrings: list[str]) -> GraderResult:
        if not substrings:
            return GraderResult(passed=True, matched=[], rationale="no expected substrings; auto-pass")
        answer_lower = answer.lower()
        matched = [s for s in substrings if s.lower() in answer_lower]
        return GraderResult(
            passed=bool(matched),
            matched=matched,
            rationale=(
                f"matched {len(matched)} of {len(substrings)} expected substrings"
                if matched
                else "no expected substrings present in answer"
            ),
        )


class LlmJudgeGrader:
    """Pass if a strong LLM judges the answer matches the rubric."""

    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def grade(self, answer: str, rubric: str, question: str) -> GraderResult:
        prompt = (
            "You judge whether an answer matches a rubric for a mechanic's question.\n\n"
            f"Question: {question}\n\n"
            f"Rubric (what a correct answer must include):\n{rubric}\n\n"
            f"Candidate answer:\n{answer}\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"passed": true | false, "rationale": "<one sentence>"}\n'
            "An answer passes only if every required element from the rubric is present "
            "(in any wording)."
        )
        for attempt in range(2):
            response = self._ollama.chat(
                [{"role": "user", "content": prompt}], self._model
            )
            parsed = _parse_json(response)
            if parsed is not None and "passed" in parsed:
                return GraderResult(
                    passed=bool(parsed["passed"]),
                    matched=[],
                    rationale=str(parsed.get("rationale", "")),
                )
            prompt = (
                "Your previous response was not valid JSON. Reply with EXACTLY one line:\n"
                '{"passed": true, "rationale": "..."}\n\n'
                f"Question: {question}\nRubric: {rubric}\nAnswer: {answer[:1500]}"
            )
        return GraderResult(
            passed=False, matched=[],
            rationale="judge output malformed twice; treating as fail",
        )
