# Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline evaluation harness that runs 27 curated questions through `AgenticChatService`, grades each answer, and reports pass@1 + source-page precision/recall + latency, broken down by failure mode. Per Anthropic's Jan 2026 guidance: build evaluation before optimizing. After this plan ships, every architecture change can be measured by re-running the harness on the new commit and diffing against the baseline.

**Architecture:** A standalone `evals/` directory — separate from `tests/` because it produces metrics, not pass/fail. The runner is a Python module invoked as `uv run python -m evals.run_evals`. It calls `AgenticChatService.ask` *as a library function* (no Typer CLI shell-out — too slow). Two grader types: `SubstringAnyGrader` (deterministic, code-only) for fact-lookup questions, `LlmJudgeGrader` (Ollama `gemma4:26b`) for procedure questions. Results are written as timestamped JSON and gitignored; only `eval_set.json` is committed. A `diff` tool compares two result files and surfaces regressions.

**Tech Stack:** Python 3.11, the existing app stack (Ollama, sqlite-vec, sentence-transformers), pytest only at the unit level. The eval runner itself is standalone.

---

## Source Spec

`docs/superpowers/specs/2026-05-01-agentic-rag-loop-design.md` — Section 5 (evaluation harness). Appendix A has the 27-entry roster.

## File Structure

**Created:**
- `evals/__init__.py` — package marker
- `evals/eval_set.json` — the 27 entries (Appendix A of the spec)
- `evals/runner.py` — orchestrates: load entries, ensure DB, run ask(), grade
- `evals/grader.py` — `SubstringAnyGrader`, `LlmJudgeGrader` (no relation to `app/rag/grader.py`)
- `evals/metrics.py` — `compute_metrics(result_records) -> dict`
- `evals/diff.py` — `compare(baseline, candidate) -> diff_dict`, plus a CLI entry-point
- `evals/run_evals.py` — `python -m evals.run_evals` script (thin wrapper around runner.py)
- `evals/seed.py` — helper that ensures vehicles + ingested PDFs exist for each entry's `vehicle_context` and `expected_source_pdf`
- `evals/results/.gitkeep` — make the directory exist
- `tests/test_evals/__init__.py`
- `tests/test_evals/test_grader.py` — unit tests for SubstringAnyGrader (LlmJudgeGrader is mocked)
- `tests/test_evals/test_metrics.py`
- `tests/test_evals/test_diff.py`

**Modified:**
- `.gitignore` — add `evals/results/*.json` (keep `.gitkeep`)
- `pyproject.toml` — `tool.pytest.ini_options.testpaths` already covers `tests/`; no change needed unless we want `tests/test_evals/` to be discovered (it should be, since it lives under `tests/`)

**No changes** to `app/`. The eval harness is read-only with respect to the application code; it imports the public service constructors and exercises them.

---

## Task 1: Skeleton + .gitignore

**Files:**
- Create: `evals/__init__.py`, `evals/results/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Create the package + results dir**

```bash
mkdir -p evals/results
touch evals/__init__.py evals/results/.gitkeep
```

- [ ] **Step 2: Gitignore generated results**

Append to `.gitignore`:

```
# Eval harness outputs (per-run JSON; only .gitkeep is tracked)
evals/results/*.json
```

- [ ] **Step 3: Verify gitignore catches results files but keeps .gitkeep**

```bash
touch evals/results/test.json
git status --short evals/
rm evals/results/test.json
```

Expected: `evals/results/.gitkeep` already tracked or shows as untracked; `test.json` does NOT show.

- [ ] **Step 4: Commit**

```bash
git add evals/__init__.py evals/results/.gitkeep .gitignore
git commit -m "chore: scaffold evals/ directory with gitignore for results"
```

---

## Task 2: Define the entry schema and write a stub `eval_set.json`

**Files:**
- Create: `evals/eval_set.json` (initially with 3 entries — fully populate in Task 8)

We start with a small subset so we can build the runner against real data without committing the 27-entry corpus until the runner works.

- [ ] **Step 1: Write the stub eval_set.json**

Create `evals/eval_set.json`:

```json
[
  {
    "id": "evt_cyl_head_004",
    "question": "What is the maximum cylinder head warpage for a 2006 Audi A8 4.2L V8?",
    "vehicle_context": {
      "year": 2006,
      "make": "Audi",
      "model": "A8 Quattro",
      "engine": "4.2L V8 (BFM)"
    },
    "expected_answer_substrings": ["0.1 mm", "0.10 mm"],
    "expected_answer_summary": null,
    "expected_source_pdf": "15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf",
    "expected_source_pages": [4],
    "failure_mode": "engine_variant_trap",
    "grader_type": "substring_any",
    "trap_note": "If retrieved from 6.0L doc, would return 0.05 mm — half the actual tolerance"
  },
  {
    "id": "evt_dtc_001",
    "question": "What does DTC P0301 mean?",
    "vehicle_context": {
      "year": 2006,
      "make": "Audi",
      "model": "A8 Quattro",
      "engine": "4.2L V8 (BFM)"
    },
    "expected_answer_substrings": ["Cylinder 1", "Misfire"],
    "expected_answer_summary": null,
    "expected_source_pdf": null,
    "expected_source_pages": [],
    "failure_mode": "exact_identifier",
    "grader_type": "substring_any",
    "trap_note": null
  },
  {
    "id": "evt_proc_002",
    "question": "What is the wheel bolt torque and tightening pattern for a 2006 Audi A8?",
    "vehicle_context": {
      "year": 2006,
      "make": "Audi",
      "model": "A8 Quattro",
      "engine": "4.2L V8 (BFM)"
    },
    "expected_answer_substrings": ["120 Nm", "diagonal"],
    "expected_answer_summary": null,
    "expected_source_pdf": null,
    "expected_source_pages": [],
    "failure_mode": "general_procedure",
    "grader_type": "substring_any",
    "trap_note": null
  }
]
```

- [ ] **Step 2: Sanity-parse the file**

Run: `uv run python -c "import json; data = json.load(open('evals/eval_set.json')); print(len(data), 'entries')"`
Expected: `3 entries`.

- [ ] **Step 3: Commit**

```bash
git add evals/eval_set.json
git commit -m "feat: add stub eval_set.json with 3 entries (full set lands later)"
```

---

## Task 3: Substring grader

**Files:**
- Create: `evals/grader.py`
- Create: `tests/test_evals/__init__.py`
- Create: `tests/test_evals/test_grader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evals/__init__.py` (empty), then `tests/test_evals/test_grader.py`:

```python
# tests/test_evals/test_grader.py
import pytest
from evals.grader import SubstringAnyGrader, LlmJudgeGrader, GraderResult


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
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_evals/test_grader.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement SubstringAnyGrader and LlmJudgeGrader stub**

Create `evals/grader.py`:

```python
# evals/grader.py
"""Graders for the evaluation harness.

SubstringAnyGrader is deterministic and offline — covers fact-lookup
questions where ground truth is a small set of expected strings (torque
values, DTC names, etc.).

LlmJudgeGrader uses gemma4:26b for procedural questions where the answer is
a multi-step procedure that can vary in wording. The judge is given a rubric
(`expected_answer_summary`) and returns pass/fail.
"""
from dataclasses import dataclass

from app.services.ollama_service import OllamaService
from app.rag.grader import _parse_json  # reuse the parser helper


@dataclass
class GraderResult:
    passed: bool
    matched: list[str]    # for SubstringAny: which substrings hit
    rationale: str        # human-readable explanation


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
    """Pass if a strong LLM (gemma4:26b) judges the answer matches the rubric."""

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
        # Fail-closed: judge couldn't be parsed → mark as failed and surface that.
        return GraderResult(
            passed=False, matched=[],
            rationale="judge output malformed twice; treating as fail",
        )
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_evals/test_grader.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Add LLM judge tests**

Append to `tests/test_evals/test_grader.py`:

```python
from unittest.mock import MagicMock
from app.services.ollama_service import OllamaService


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
```

Run: `uv run pytest tests/test_evals/test_grader.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add evals/grader.py tests/test_evals/__init__.py tests/test_evals/test_grader.py
git commit -m "feat: add eval substring/llm-judge graders"
```

---

## Task 4: Metrics computation

**Files:**
- Create: `evals/metrics.py`
- Create: `tests/test_evals/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evals/test_metrics.py`:

```python
# tests/test_evals/test_metrics.py
from evals.metrics import compute_metrics


def _record(
    *,
    id: str = "x",
    failure_mode: str = "general_procedure",
    passed: bool = True,
    iterations: int = 1,
    latency_s: float = 1.0,
    sources: list[dict] | None = None,
    expected_pdf: str | None = None,
    expected_pages: list[int] | None = None,
):
    return {
        "id": id,
        "failure_mode": failure_mode,
        "passed": passed,
        "iterations": iterations,
        "latency_s": latency_s,
        "sources": sources or [],
        "expected_source_pdf": expected_pdf,
        "expected_source_pages": expected_pages or [],
    }


def test_compute_metrics_overall_pass_at_1():
    records = [_record(passed=True), _record(passed=False), _record(passed=True)]
    m = compute_metrics(records)
    assert m["overall"]["pass_at_1"] == 2 / 3


def test_compute_metrics_per_failure_mode():
    records = [
        _record(failure_mode="table_spec", passed=True),
        _record(failure_mode="table_spec", passed=False),
        _record(failure_mode="negative", passed=True),
    ]
    m = compute_metrics(records)
    assert m["by_failure_mode"]["table_spec"]["pass_at_1"] == 0.5
    assert m["by_failure_mode"]["negative"]["pass_at_1"] == 1.0


def test_compute_metrics_source_page_precision_and_recall():
    """Precision: of returned (pdf, page) pairs, fraction that are expected.
    Recall: fraction of expected pages covered by returned sources."""
    records = [
        _record(
            sources=[{"filename": "manual.pdf", "page": 4}, {"filename": "manual.pdf", "page": 99}],
            expected_pdf="manual.pdf",
            expected_pages=[4, 5],
        ),
    ]
    m = compute_metrics(records)
    # Precision: 1 of 2 returned matches → 0.5.
    assert m["overall"]["source_page_precision"] == 0.5
    # Recall: 1 of 2 expected covered → 0.5.
    assert m["overall"]["source_page_recall"] == 0.5


def test_compute_metrics_skips_source_metrics_when_no_expectation():
    records = [_record(sources=[{"filename": "x.pdf", "page": 1}], expected_pdf=None)]
    m = compute_metrics(records)
    # When expected_source_pdf is None, the entry doesn't contribute to source metrics.
    assert m["overall"]["source_page_precision"] is None
    assert m["overall"]["source_page_recall"] is None


def test_compute_metrics_mean_iterations_and_latency():
    records = [
        _record(iterations=1, latency_s=2.0),
        _record(iterations=3, latency_s=4.0),
    ]
    m = compute_metrics(records)
    assert m["overall"]["mean_iterations"] == 2.0
    assert m["overall"]["mean_latency_s"] == 3.0


def test_compute_metrics_handles_empty_input():
    m = compute_metrics([])
    assert m["overall"]["pass_at_1"] == 0.0
    assert m["overall"]["count"] == 0
    assert m["by_failure_mode"] == {}
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_evals/test_metrics.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement compute_metrics**

Create `evals/metrics.py`:

```python
# evals/metrics.py
"""Aggregate per-entry result records into pass@1 + source metrics."""
from collections import defaultdict
from statistics import mean


def compute_metrics(records: list[dict]) -> dict:
    """Aggregate result records produced by the eval runner.

    Each record contains:
        id, failure_mode, passed, iterations, latency_s, sources,
        expected_source_pdf, expected_source_pages

    Returns a dict with overall + per-failure-mode breakdowns.
    """
    if not records:
        return {
            "overall": {
                "count": 0,
                "pass_at_1": 0.0,
                "mean_iterations": 0.0,
                "mean_latency_s": 0.0,
                "source_page_precision": None,
                "source_page_recall": None,
            },
            "by_failure_mode": {},
        }

    overall = _aggregate_one("overall", records)

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_mode[r["failure_mode"]].append(r)

    by_failure_mode = {mode: _aggregate_one(mode, recs) for mode, recs in by_mode.items()}

    return {"overall": overall, "by_failure_mode": by_failure_mode}


def _aggregate_one(label: str, records: list[dict]) -> dict:
    count = len(records)
    pass_at_1 = sum(1 for r in records if r["passed"]) / count
    mean_iter = mean(r["iterations"] for r in records)
    mean_latency = mean(r["latency_s"] for r in records)

    # Source-page metrics only over records that specify expected_source_pdf.
    source_relevant = [r for r in records if r.get("expected_source_pdf")]
    if source_relevant:
        precisions = []
        recalls = []
        for r in source_relevant:
            expected_pairs = {(r["expected_source_pdf"], p) for p in r["expected_source_pages"]}
            returned_pairs = {(s["filename"], s["page"]) for s in r["sources"] if s.get("page") is not None}
            if returned_pairs:
                precisions.append(len(expected_pairs & returned_pairs) / len(returned_pairs))
            else:
                precisions.append(0.0)
            if expected_pairs:
                recalls.append(len(expected_pairs & returned_pairs) / len(expected_pairs))
            else:
                recalls.append(0.0)
        page_precision = mean(precisions) if precisions else None
        page_recall = mean(recalls) if recalls else None
    else:
        page_precision = None
        page_recall = None

    return {
        "count": count,
        "pass_at_1": pass_at_1,
        "mean_iterations": mean_iter,
        "mean_latency_s": mean_latency,
        "source_page_precision": page_precision,
        "source_page_recall": page_recall,
    }
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_evals/test_metrics.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/metrics.py tests/test_evals/test_metrics.py
git commit -m "feat: add eval metrics aggregator"
```

---

## Task 5: Diff tool

**Files:**
- Create: `evals/diff.py`
- Create: `tests/test_evals/test_diff.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_evals/test_diff.py`:

```python
# tests/test_evals/test_diff.py
from evals.diff import compare_results


def test_compare_results_lists_regressions_and_new_passes():
    baseline = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": False},
            {"id": "c", "failure_mode": "y", "passed": True},
        ],
    }
    candidate = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": False},  # regressed
            {"id": "b", "failure_mode": "x", "passed": True},   # new pass
            {"id": "c", "failure_mode": "y", "passed": True},   # unchanged
        ],
    }
    diff = compare_results(baseline, candidate)

    assert diff["regressed"] == [{"id": "a", "failure_mode": "x"}]
    assert diff["newly_passing"] == [{"id": "b", "failure_mode": "x"}]
    assert diff["unchanged"] == [{"id": "c", "failure_mode": "y", "passed": True}]


def test_compare_results_pass_rate_delta_per_failure_mode():
    baseline = {
        "records": [
            {"id": "a1", "failure_mode": "table_spec", "passed": False},
            {"id": "a2", "failure_mode": "table_spec", "passed": True},
        ],
    }
    candidate = {
        "records": [
            {"id": "a1", "failure_mode": "table_spec", "passed": True},
            {"id": "a2", "failure_mode": "table_spec", "passed": True},
        ],
    }
    diff = compare_results(baseline, candidate)
    assert diff["pass_rate_delta"]["table_spec"] == 0.5  # 50% → 100% → +0.5


def test_compare_results_handles_entry_added_only_in_candidate():
    baseline = {"records": [{"id": "a", "failure_mode": "x", "passed": True}]}
    candidate = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": True},  # new entry
        ],
    }
    diff = compare_results(baseline, candidate)
    assert diff["only_in_candidate"] == [{"id": "b", "failure_mode": "x"}]


def test_compare_results_handles_entry_dropped_from_candidate():
    baseline = {
        "records": [
            {"id": "a", "failure_mode": "x", "passed": True},
            {"id": "b", "failure_mode": "x", "passed": False},
        ],
    }
    candidate = {"records": [{"id": "a", "failure_mode": "x", "passed": True}]}
    diff = compare_results(baseline, candidate)
    assert diff["only_in_baseline"] == [{"id": "b", "failure_mode": "x"}]
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_evals/test_diff.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement compare_results + a CLI entry-point**

Create `evals/diff.py`:

```python
# evals/diff.py
"""Compare two eval result files and surface regressions, gains, and pass-rate deltas.

Used as a library function (compare_results) and as a CLI:
    uv run python -m evals.diff baseline.json candidate.json
"""
import argparse
import json
import sys
from collections import defaultdict


def compare_results(baseline: dict, candidate: dict) -> dict:
    base_by_id = {r["id"]: r for r in baseline["records"]}
    cand_by_id = {r["id"]: r for r in candidate["records"]}

    common_ids = set(base_by_id) & set(cand_by_id)
    only_baseline = sorted(set(base_by_id) - set(cand_by_id))
    only_candidate = sorted(set(cand_by_id) - set(base_by_id))

    regressed = []
    newly_passing = []
    unchanged = []
    for entry_id in sorted(common_ids):
        b = base_by_id[entry_id]
        c = cand_by_id[entry_id]
        summary = {"id": entry_id, "failure_mode": c["failure_mode"]}
        if b["passed"] and not c["passed"]:
            regressed.append(summary)
        elif not b["passed"] and c["passed"]:
            newly_passing.append(summary)
        else:
            unchanged.append({**summary, "passed": c["passed"]})

    pass_rate_delta = _pass_rate_delta_per_mode(baseline, candidate)

    return {
        "regressed": regressed,
        "newly_passing": newly_passing,
        "unchanged": unchanged,
        "only_in_baseline": [
            {"id": i, "failure_mode": base_by_id[i]["failure_mode"]} for i in only_baseline
        ],
        "only_in_candidate": [
            {"id": i, "failure_mode": cand_by_id[i]["failure_mode"]} for i in only_candidate
        ],
        "pass_rate_delta": pass_rate_delta,
    }


def _pass_rate_delta_per_mode(baseline: dict, candidate: dict) -> dict[str, float]:
    """Per failure_mode: candidate_pass_rate - baseline_pass_rate."""
    def rates(records):
        groups: dict[str, list[bool]] = defaultdict(list)
        for r in records:
            groups[r["failure_mode"]].append(r["passed"])
        return {mode: sum(passes) / len(passes) for mode, passes in groups.items()}

    base_rates = rates(baseline["records"])
    cand_rates = rates(candidate["records"])
    modes = set(base_rates) | set(cand_rates)
    return {m: cand_rates.get(m, 0.0) - base_rates.get(m, 0.0) for m in sorted(modes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff two eval result files.")
    parser.add_argument("baseline", help="Path to baseline result JSON.")
    parser.add_argument("candidate", help="Path to candidate result JSON.")
    args = parser.parse_args(argv)

    with open(args.baseline) as f:
        baseline = json.load(f)
    with open(args.candidate) as f:
        candidate = json.load(f)

    diff = compare_results(baseline, candidate)
    print(json.dumps(diff, indent=2))
    # Exit non-zero if there are regressions — useful for CI gating.
    return 1 if diff["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_evals/test_diff.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/diff.py tests/test_evals/test_diff.py
git commit -m "feat: add eval result diff tool"
```

---

## Task 6: Seed helper — vehicle lookup only

**Files:**
- Create: `evals/seed.py`

The runner assumes vehicles + their manuals are already in the DB (the user adds them with `vehicle add` + `document add --recursive` as part of normal setup; that's how a vehicle's manuals get loaded in the first place). This module provides one helper: `find_vehicle()` resolves an entry's `vehicle_context` to a vehicle id and raises a clear error if the vehicle is missing — no auto-create, no per-entry PDF ingestion. `expected_source_pdf` on each entry is metric input only, never an ingestion trigger.

The eval DB is `./data/app.db` — the same one chat uses. The runner is read-only with respect to the corpus.

- [ ] **Step 1: Write the seed module**

Create `evals/seed.py`:

```python
# evals/seed.py
"""Seed helpers for the eval runner.

ensure_vehicle() finds-or-creates a vehicle row matching the entry's
vehicle_context. ensure_pdf_ingested() ingests the named PDF for that
vehicle if no Document row already exists for it. Both are cached per run
to avoid duplicate work across entries that share a vehicle/document.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import Document
from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository

# Module-level caches (one run = one process).
_vehicle_cache: dict[tuple, int] = {}
_document_cache: set[tuple[int, str]] = set()


def ensure_vehicle(session: Session, ctx: dict) -> int:
    key = (ctx["year"], ctx["make"], ctx["model"], ctx["engine"])
    if key in _vehicle_cache:
        return _vehicle_cache[key]

    existing = (
        session.query(Vehicle)
        .filter_by(year=ctx["year"], make=ctx["make"], model=ctx["model"], engine=ctx["engine"])
        .first()
    )
    if existing is not None:
        _vehicle_cache[key] = existing.id
        return existing.id

    vehicle = VehicleRepository(session).create(
        year=ctx["year"], make=ctx["make"], model=ctx["model"], engine=ctx["engine"],
    )
    session.flush()
    _vehicle_cache[key] = vehicle.id
    return vehicle.id


def ensure_pdf_ingested(
    session: Session,
    vehicle_id: int,
    pdf_filename: str,
    docs_dir: str,
    document_service,
) -> None:
    """Ingest the named PDF for the vehicle if not already present.

    pdf_filename is the bare basename (e.g. "15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf").
    The harness searches for it under settings.docs_dir recursively.
    """
    cache_key = (vehicle_id, pdf_filename)
    if cache_key in _document_cache:
        return

    existing = (
        session.query(Document)
        .filter_by(vehicle_id=vehicle_id, file_name=pdf_filename, processing_status="ready")
        .first()
    )
    if existing is not None:
        _document_cache.add(cache_key)
        return

    candidates = list(Path(docs_dir).rglob(pdf_filename))
    if not candidates:
        raise FileNotFoundError(
            f"PDF not found: {pdf_filename} (searched under {docs_dir} recursively). "
            "Place the file there before running evals."
        )
    document_service.add_document(vehicle_id=vehicle_id, pdf_path=str(candidates[0]))
    session.flush()
    _document_cache.add(cache_key)


def reset_caches() -> None:
    """Clear the module caches — call at the start of each new runner invocation."""
    _vehicle_cache.clear()
    _document_cache.clear()
```

- [ ] **Step 2: Sanity-import**

Run: `uv run python -c "from evals.seed import ensure_vehicle, ensure_pdf_ingested, reset_caches; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add evals/seed.py
git commit -m "feat: add eval seed helpers for vehicle/document setup"
```

---

## Task 7: The runner

**Files:**
- Create: `evals/runner.py`
- Create: `evals/run_evals.py`

The runner orchestrates everything: load entries, seed vehicle + docs per entry, call `AgenticChatService.ask`, grade, collect timing, write a results JSON.

- [ ] **Step 1: Implement the runner**

Create `evals/runner.py`:

```python
# evals/runner.py
"""End-to-end eval runner.

Loads eval_set.json, ensures each entry's vehicle + PDFs are present,
calls AgenticChatService.ask() as a library function, grades the result,
and writes a JSON results file.
"""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_engine
from app.db.migrations import apply_hybrid_retrieval_migration
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.chunk_repository import ChunkRepository
from app.rag.grader import GroundednessGrader, RelevanceGrader
from app.rag.query_rewriter import QueryRewriter
from app.services.agentic_chat_service import AgenticChatService
from app.services.contextualization_service import ContextualizationService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.metadata_extractor import MetadataExtractor
from app.services.ollama_service import OllamaService
from app.services.pdf_service import PDFService
from app.services.reranker import BgeReranker
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.table_chunker import TableChunker
from evals.grader import LlmJudgeGrader, SubstringAnyGrader
from evals.seed import ensure_pdf_ingested, ensure_vehicle, reset_caches

import app.models  # noqa: F401 — register models with Base


def run(
    eval_set_path: str = "evals/eval_set.json",
    output_path: str | None = None,
) -> str:
    """Run the full eval set against the current main DB. Returns the output path."""
    reset_caches()

    entries = json.loads(Path(eval_set_path).read_text())

    engine = get_engine(f"sqlite:///{settings.db_path}")
    Base.metadata.create_all(engine)
    apply_hybrid_retrieval_migration(engine, vec_dim=settings.vec_dim)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    ollama = OllamaService(settings.ollama_base_url)
    embedding = EmbeddingService(ollama, settings.embed_model)
    reranker = BgeReranker(model_name=settings.reranker_model)
    substring_grader = SubstringAnyGrader()
    judge_grader = LlmJudgeGrader(ollama, settings.chat_model)

    records: list[dict] = []
    for entry in entries:
        with Session() as session:
            vehicle_id = ensure_vehicle(session, entry["vehicle_context"])

            doc_service = _build_document_service(session, ollama, embedding)
            if entry.get("expected_source_pdf"):
                ensure_pdf_ingested(
                    session, vehicle_id, entry["expected_source_pdf"],
                    settings.docs_dir, doc_service,
                )
            session.commit()

        with Session() as session:
            job = JobRepository(session).create(vehicle_id=vehicle_id, title=f"eval:{entry['id']}")
            session.flush()

            chat_svc = _build_chat_service(session, ollama, embedding, reranker)
            t0 = time.monotonic()
            try:
                result = chat_svc.ask(job_id=job.id, question=entry["question"])
                error = None
            except Exception as exc:
                result = None
                error = repr(exc)
            elapsed = time.monotonic() - t0
            session.commit()

        graded = _grade(entry, result, substring_grader, judge_grader)
        records.append({
            "id": entry["id"],
            "failure_mode": entry["failure_mode"],
            "question": entry["question"],
            "passed": graded.passed if result is not None else False,
            "rationale": graded.rationale if result is not None else f"runtime error: {error}",
            "iterations": len(result.trace) if result is not None else 0,
            "latency_s": elapsed,
            "answer": result.answer if result is not None else None,
            "sources": result.sources if result is not None else [],
            "expected_source_pdf": entry.get("expected_source_pdf"),
            "expected_source_pages": entry.get("expected_source_pages", []),
            "error": error,
        })

    output_path = output_path or _default_output_path()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "records": records,
    }, indent=2))
    return output_path


def _build_document_service(session, ollama, embedding) -> DocumentService:
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(settings.chunk_size, settings.chunk_overlap),
        table_chunker=TableChunker(),
        contextualization_service=ContextualizationService(ollama, settings.context_model),
        embedding_service=embedding,
        metadata_extractor=MetadataExtractor(ollama, settings.context_model),
        docs_dir=settings.docs_dir,
    )


def _build_chat_service(session, ollama, embedding, reranker) -> AgenticChatService:
    retrieval = HybridRetrievalService(
        session=session,
        embedding_service=embedding,
        bm25_top_k=settings.bm25_top_k,
        vector_top_k=settings.vector_top_k,
        rrf_k=settings.rrf_k,
        result_top_k=max(settings.bm25_top_k, settings.vector_top_k),
    )
    return AgenticChatService(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval_service=retrieval,
        reranker=reranker,
        relevance_grader=RelevanceGrader(ollama, settings.context_model),
        groundedness_grader=GroundednessGrader(ollama, settings.context_model),
        query_rewriter=QueryRewriter(ollama, settings.context_model),
        ollama_service=ollama,
        chat_model=settings.chat_model,
        recent_messages_limit=settings.recent_messages,
        max_iterations=settings.max_loop_iterations,
        rerank_top_k=settings.rerank_top_k,
        verbose=False,  # quiet for batch runs
    )


def _grade(entry: dict, result, substring, judge):
    if result is None:
        from evals.grader import GraderResult
        return GraderResult(passed=False, matched=[], rationale="runtime error during ask()")
    if entry["grader_type"] == "llm_judge":
        return judge.grade(
            answer=result.answer,
            rubric=entry.get("expected_answer_summary") or "",
            question=entry["question"],
        )
    return substring.grade(
        answer=result.answer,
        substrings=entry.get("expected_answer_substrings") or [],
    )


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _default_output_path() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sha = _git_sha()[:8]
    return f"evals/results/{ts}-{sha}.json"
```

- [ ] **Step 2: Add the script entry-point**

Create `evals/run_evals.py`:

```python
# evals/run_evals.py
"""CLI entry-point: `uv run python -m evals.run_evals [--out FILE]`."""
import argparse
import json
import sys
from pathlib import Path

from evals.metrics import compute_metrics
from evals.runner import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the eval set against the current branch.")
    parser.add_argument(
        "--out", default=None,
        help="Output JSON path. Defaults to evals/results/<ts>-<sha>.json.",
    )
    parser.add_argument(
        "--eval-set", default="evals/eval_set.json",
        help="Path to eval_set.json.",
    )
    args = parser.parse_args(argv)

    output_path = run(eval_set_path=args.eval_set, output_path=args.out)
    payload = json.loads(Path(output_path).read_text())
    metrics = compute_metrics(payload["records"])

    print(f"\nResults written to: {output_path}\n")
    print(f"Overall pass@1: {metrics['overall']['pass_at_1']:.2%} "
          f"({metrics['overall']['count']} entries)")
    print(f"Mean iterations: {metrics['overall']['mean_iterations']:.2f}")
    print(f"Mean latency: {metrics['overall']['mean_latency_s']:.2f}s")
    if metrics['overall']['source_page_precision'] is not None:
        print(f"Source-page precision: {metrics['overall']['source_page_precision']:.2%}")
        print(f"Source-page recall: {metrics['overall']['source_page_recall']:.2%}")

    print("\nBy failure mode:")
    for mode, m in sorted(metrics["by_failure_mode"].items()):
        print(f"  {mode:24s}  pass@1 = {m['pass_at_1']:.0%}  ({m['count']} entries)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Quick sanity-import**

Run: `uv run python -c "from evals.runner import run; from evals.run_evals import main; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add evals/runner.py evals/run_evals.py
git commit -m "feat: add eval runner and CLI entry-point"
```

---

## Task 8: Populate the full 27-entry eval_set.json

**Files:**
- Modify: `evals/eval_set.json`

The full 27-entry roster lives in spec Appendix A. Each entry needs the same schema as Task 2's stubs. We populate from spec metadata.

A practical wrinkle: many specs reference real PDF page numbers that exist in the user's local corpus. We don't pin those numbers to the eval entries unless the spec records them — in cases where `expected_source_pages` is unknown, set it to `[]` and rely on substring matching alone. The source-page metric will simply skip those entries (Task 4 handles `expected_source_pdf=None`).

- [ ] **Step 1: Replace evals/eval_set.json with the full set**

This is bulky but necessary — every entry must be self-contained, no placeholders. Replace `evals/eval_set.json` with the full 27 entries, structured per Section 5 of the spec. Use this template per entry:

```json
{
  "id": "<spec id>",
  "question": "<full question with vehicle context>",
  "vehicle_context": {"year": 2006, "make": "Audi", "model": "A8 Quattro", "engine": "<engine>"},
  "expected_answer_substrings": ["<key value 1>", "<key value 2>"],
  "expected_answer_summary": null,
  "expected_source_pdf": "<pdf basename or null>",
  "expected_source_pages": [<page>],
  "failure_mode": "<one of the 7 modes>",
  "grader_type": "substring_any",
  "trap_note": "<spec note or null>"
}
```

Authoring rules:
- Engine variant trap entries (8): use the matching engine in `vehicle_context.engine`. Each pair shares a question template but different vehicles.
- Negative entries (3): `expected_answer_substrings` ≈ ["could not find", "not in", "manual does not"] — system must refuse, not invent.
- LLM-judge entry: `evt_proc_003` (Front brake pad replacement procedure). Set `grader_type: "llm_judge"`, `expected_answer_substrings: []`, `expected_answer_summary` = a one-paragraph rubric describing required steps.

The full content is the spec's Appendix A. Each entry's `failure_mode` aligns with the spec table in Section 5 ("Distribution of the 27 entries"). The exact substring values come from the spec's per-entry notes (e.g. `evt_cyl_head_002`: "10 Nm", `evt_cyl_head_003`: "8 Nm", etc.).

To save time during plan execution, the engineer can author this in two passes:
1. First pass: rough JSON with stub substrings → runner runs → see which entries are mis-scored.
2. Second pass: refine substrings based on the actual answers the system produces (a substring grader is meaningful only if its expected list matches how the model phrases the answer).

Don't iterate too long: the goal is to commit a working baseline. Two refinement passes is enough.

- [ ] **Step 2: Validate JSON**

Run: `uv run python -c "import json; entries = json.load(open('evals/eval_set.json')); print(len(entries), 'entries')"`
Expected: `27 entries`.

- [ ] **Step 3: Sanity-check all required fields are present**

Run:
```bash
uv run python -c "
import json
entries = json.load(open('evals/eval_set.json'))
required = ['id', 'question', 'vehicle_context', 'expected_answer_substrings',
            'expected_source_pdf', 'expected_source_pages', 'failure_mode', 'grader_type']
for e in entries:
    missing = [k for k in required if k not in e]
    if missing:
        print(f'Entry {e.get(\"id\")} missing: {missing}')
print('all entries validated')
"
```

Expected: `all entries validated`.

- [ ] **Step 4: Confirm distribution matches spec table**

Run:
```bash
uv run python -c "
import json
from collections import Counter
entries = json.load(open('evals/eval_set.json'))
c = Counter(e['failure_mode'] for e in entries)
for mode, count in sorted(c.items()):
    print(f'  {mode}: {count}')
print(f'  total: {sum(c.values())}')
"
```

Expected (per spec Section 5):

```
  engine_variant_trap: 8
  exact_identifier: 3
  general_procedure: 3
  multi_hop: 2
  negative: 3
  procedural_prose: 2
  table_spec: 6
  total: 27
```

- [ ] **Step 5: Commit**

```bash
git add evals/eval_set.json
git commit -m "feat: populate eval_set.json with the full 27-entry roster"
```

---

## Task 9: Baseline run

**Goal:** Capture the first eval result so future runs have something to diff against. Manual.

- [ ] **Step 1: Pre-flight (one-time corpus setup)**

The runner assumes vehicles and their manuals are already ingested. For each `vehicle_context` referenced by the eval set:

```bash
uv run mechanic-sidekick vehicle add   # 2006 Audi A8 Quattro, "4.2L V8 (BFM)"
uv run mechanic-sidekick vehicle add   # 2006 Audi A8 Quattro, "6.0L W12 (BSB)"
uv run mechanic-sidekick document add 1 <path-to-4.2L-manuals> --recursive
uv run mechanic-sidekick document add 2 <path-to-6.0L-manuals> --recursive
```

The engine string must match the eval entry exactly. If you're starting clean, `mechanic-sidekick db reset --yes` first.

- [ ] **Step 2: Run the harness**

```bash
uv run python -m evals.run_evals --out evals/results/baseline.json
```

Expected: takes 15-45 minutes (27 entries × ingest-on-first-touch + 27 chat round-trips + grading). Final summary printed: pass@1, per-failure-mode breakdown, mean iterations, latency.

- [ ] **Step 3: Inspect failures**

```bash
uv run python -c "
import json
data = json.load(open('evals/results/baseline.json'))
for r in data['records']:
    if not r['passed']:
        print(f\"{r['id']}  ({r['failure_mode']})  iter={r['iterations']}  latency={r['latency_s']:.1f}s\")
        print(f\"  Q: {r['question']}\")
        print(f\"  A: {r['answer'][:200] if r['answer'] else '(error)'}\")
        print(f\"  Why: {r['rationale']}\")
        print()
"
```

Expected: list of failed entries with their answers and rationales. Use this to refine `expected_answer_substrings` if any entry is "right but mis-scored."

- [ ] **Step 4: Re-run after substring refinement (optional)**

If you found mis-scored entries:
- Edit `evals/eval_set.json` substrings.
- Run again: `uv run python -m evals.run_evals --out evals/results/baseline-v2.json`
- Diff the two: `uv run python -m evals.diff evals/results/baseline.json evals/results/baseline-v2.json`

- [ ] **Step 5: No commit for the result file**

`evals/results/*.json` is gitignored. The baseline lives on disk for the next branch's diff.

If you refined substrings, commit the schema fixes:

```bash
git add evals/eval_set.json
git commit -m "fix: tighten eval substrings based on baseline run"
```

---

## Task 10: A/B run after each architecture change

**Goal:** Document the workflow for using the harness as a gating signal. No code; this is a procedure.

The workflow per the spec:

```bash
# Baseline (capture before the change)
git switch main
uv run python -m evals.run_evals --out evals/results/baseline.json

# Candidate (the branch with your change)
git switch feature/whatever
uv run python -m evals.run_evals --out evals/results/feature.json

# Diff
uv run python -m evals.diff evals/results/baseline.json evals/results/feature.json
```

Merge gating: pass@1 must not regress on any failure_mode. The diff tool exits non-zero when there are regressions, so it can be wired into a pre-merge check.

- [ ] **Step 1: Document the workflow**

Add a small note to `README.md` if you want — but the spec already covers it. Skip if not desired.

- [ ] **Step 2: No commit**

Procedural only.

---

## Self-Review Checklist (run before marking Plan 4 done)

- [ ] Spec section 5 — eval_set.json schema (Task 2) + runner (Task 7) + grader.py with both grader types (Task 3) + metrics.py (Task 4) + diff.py (Task 5) + 27 entries (Task 8) + workflow (Task 10).
- [ ] Spec "Crucial constraint" — eval harness is *additional* to unit tests, not a replacement. Confirmed: `tests/test_evals/` covers grader/metrics/diff at the unit level; `evals/runner.py` exercises end-to-end against real Ollama.
- [ ] Distribution matches spec table — verified in Task 8 step 4.
- [ ] Result files gitignored (Task 1).
- [ ] No placeholders. Type names consistent: `SubstringAnyGrader.grade(answer, substrings) -> GraderResult`; `LlmJudgeGrader.grade(answer, rubric, question) -> GraderResult`; `compute_metrics(records) -> dict`; `compare_results(baseline, candidate) -> dict`. Result schema (the dict in `records`) consistent across runner/metrics/diff (`id`, `failure_mode`, `passed`, `iterations`, `latency_s`, `sources`, `expected_source_pdf`, `expected_source_pages`).
- [ ] Runner imports the same service constructors the CLI uses — no parallel wiring.
- [ ] The 27th entry is `evt_assembly_007` per spec Appendix A. Total in `evals/eval_set.json` = 27 (Task 8 step 2).
