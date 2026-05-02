# Agentic Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ChatService` (single-pass retrieve-then-generate) with `AgenticChatService` — a bounded state machine that grades retrieved chunks for relevance, hard-rejects engine-variant mismatches, regenerates the query when no chunk passes, generates an answer, then grades that answer for groundedness, with up to 2 retry iterations.

**Architecture:** A single Python module owns the loop (`agentic_chat_service.py`). Three stateless graders (`RelevanceGrader`, `GroundednessGrader`, `QueryRewriter`) live in `app/rag/` — each is a thin wrapper over `OllamaService` returning structured JSON. The loop is an explicit `for iteration in range(MAX + 1)` — no framework. Verbose UX prints every state transition through `app/utils/console.py`. State is held in a frozen-ish dataclass `LoopState` so each iteration's transition is auditable.

**Tech Stack:** Python 3.11, Ollama (`gemma4:e4b` graders, `gemma4:26b` generator), Pydantic for grader output schemas, Rich for verbose console output, pytest with `MagicMock(spec=...)` for Ollama.

---

## Source Spec

`docs/superpowers/specs/2026-05-01-agentic-rag-loop-design.md` — Section 4 (the agentic loop). Depends on Plan 1 (chunk metadata, FTS5 + vec0 tables) and Plan 2 (`HybridRetrievalService`, `Reranker` protocol).

## File Structure

**Created:**
- `app/rag/grader.py` — `RelevanceGrader` and `GroundednessGrader`, both with structured JSON output and fail-open/fail-closed semantics
- `app/rag/query_rewriter.py` — `QueryRewriter`
- `app/rag/loop_state.py` — `LoopState` dataclass + `LoopTraceEntry` dataclass (returned to the caller)
- `app/services/agentic_chat_service.py` — the bounded state machine
- `tests/test_rag/test_grader.py`
- `tests/test_rag/test_query_rewriter.py`
- `tests/test_services/test_agentic_chat_service.py`

**Modified:**
- `app/utils/console.py` — add `print_loop_step` helpers for the verbose trace
- `app/cli.py` — `_make_chat_service` returns `AgenticChatService` and wires hybrid retrieval + reranker + graders
- `app/config.py` — add `max_loop_iterations`, `loop_verbose`
- `app/rag/prompt_builder.py` — `build_messages` no longer needs to wedge engine-variant warnings into the system prompt (the grader handles that). System prompt is simplified.

**Deleted:**
- `app/services/retrieval_service.py` (postponed from Plan 2)
- `app/rag/similarity.py` (postponed from Plan 2)
- `app/services/chat_service.py` (replaced by `AgenticChatService`)
- `tests/test_services/test_chat_service.py` (covered by `test_agentic_chat_service.py`)

---

## Task 1: Delete the obsolete chat path

**Files:**
- Delete: `app/services/chat_service.py`
- Delete: `app/services/retrieval_service.py`
- Delete: `app/rag/similarity.py`
- Delete: `tests/test_services/test_chat_service.py`
- Modify: `app/cli.py` (`_make_chat_service` becomes a stub that raises until Task 8 wires the new service)

This task is the high-water mark: after this commit, the `chat ask` and `chat start` commands raise until Task 8 lands. That's intentional — we delete first so we don't have two parallel chat paths confusing the test suite.

- [ ] **Step 1: Confirm nothing else imports the doomed modules**

```bash
grep -rn "RetrievalService\|app.services.retrieval_service" app/ tests/
grep -rn "ChatService\|app.services.chat_service" app/ tests/
grep -rn "rag.similarity\|cosine_similarity\|rank_chunks" app/ tests/
```

Expected matches: the four files listed above plus `app/cli.py`. The CLI gets stubbed in step 3.

- [ ] **Step 2: Delete the modules**

```bash
git rm app/services/chat_service.py
git rm app/services/retrieval_service.py
git rm app/rag/similarity.py
git rm tests/test_services/test_chat_service.py
```

- [ ] **Step 3: Stub _make_chat_service in app/cli.py**

In `app/cli.py`, replace `_make_chat_service` with:

```python
def _make_chat_service(session):
    """Stub during Plan 3 implementation; real wiring lands in Task 8."""
    raise NotImplementedError(
        "AgenticChatService wiring is in progress (Plan 3, Task 8). "
        "The chat commands are temporarily unavailable on this branch."
    )
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/ -v`
Expected: green. (We deleted the tests that depended on the removed modules.)

- [ ] **Step 5: Commit**

```bash
git add app/cli.py
git commit -m "chore: delete pre-loop ChatService/RetrievalService and similarity helper"
```

---

## Task 2: LoopState + LoopTraceEntry dataclasses

**Files:**
- Create: `app/rag/loop_state.py`

These types are tiny but they thread through the loop's signatures, so we land them as a single commit before writing the loop body.

- [ ] **Step 1: Create the module**

Create `app/rag/loop_state.py`:

```python
# app/rag/loop_state.py
"""State and trace types used by AgenticChatService.

LoopState is the working state held across iterations of the loop.
LoopTraceEntry records what happened in a single iteration so the CLI can
print it verbosely and a future evaluation harness can replay the trace.
"""
from dataclasses import dataclass, field

from app.models.document_chunk import DocumentChunk


@dataclass
class GradingResult:
    """Per-chunk relevance grading output."""
    chunk: DocumentChunk
    relevant: bool
    reason: str


@dataclass
class LoopTraceEntry:
    """One iteration of the loop, ready to render in verbose mode."""
    iteration: int
    query: str
    candidate_count: int           # after hybrid retrieval
    reranked_count: int            # after cross-encoder
    relevant_count: int            # after relevance grader
    rejected_reasons: dict[str, int]  # reason → count, e.g. {"engine variant mismatch": 3}
    rewritten_query: str | None = None
    rewrite_rationale: str | None = None
    generated_answer: str | None = None  # only on the iteration that generates
    groundedness_pass: bool | None = None
    groundedness_unsupported: list[str] | None = None


@dataclass
class LoopState:
    """Working state across iterations.

    Once instantiated, only `current_query`, `iteration`, `rejected_chunk_ids`,
    and `failure_reasons` mutate. `original_question` is immutable — the
    rewriter conditions on the original each time, never on the previous
    rewrite, to prevent drift.
    """
    original_question: str
    current_query: str
    iteration: int = 0
    rejected_chunk_ids: set[int] = field(default_factory=set)
    failure_reasons: list[str] = field(default_factory=list)
    trace: list[LoopTraceEntry] = field(default_factory=list)
```

- [ ] **Step 2: Sanity-import**

Run: `uv run python -c "from app.rag.loop_state import LoopState, LoopTraceEntry, GradingResult; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/rag/loop_state.py
git commit -m "feat: add LoopState and LoopTraceEntry dataclasses"
```

---

## Task 3: RelevanceGrader

**Files:**
- Create: `app/rag/grader.py`
- Create: `tests/test_rag/test_grader.py`

`RelevanceGrader.grade(chunk, question, vehicle)` returns `GradingResult`. The prompt explicitly hands it `chunk.engine_variant` and `vehicle.engine` and instructs hard-reject on mismatch. Output JSON: `{"relevant": bool, "reason": str}`. Fail-open on malformed output (per spec) — better to leak a candidate than lose it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rag/test_grader.py`:

```python
# tests/test_rag/test_grader.py
import pytest
from unittest.mock import MagicMock

from app.models.document_chunk import DocumentChunk
from app.models.vehicle import Vehicle
from app.rag.grader import RelevanceGrader, GroundednessGrader
from app.services.ollama_service import OllamaService


def _vehicle(engine: str = "4.2L V8") -> Vehicle:
    return Vehicle(year=2006, make="Audi", model="A8", engine=engine)


def _chunk(content: str, engine_variant: str | None = None) -> DocumentChunk:
    return DocumentChunk(
        document_id=1, chunk_index=0, content=content, engine_variant=engine_variant,
    )


# --- RelevanceGrader -----------------------------------------------------------

def test_relevance_grader_returns_relevant_true_when_llm_says_so():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "answers the question"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("Head bolt torque 129 Nm", "4.2L"), "head bolt torque?", _vehicle("4.2L V8"))
    assert out.relevant is True
    assert out.reason == "answers the question"


def test_relevance_grader_hard_rejects_engine_variant_mismatch_without_calling_llm():
    """Spec Q6: hard side - if chunk variant differs from vehicle, reject locally."""
    ollama = MagicMock(spec=OllamaService)
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Head bolt torque 95 Nm", engine_variant="6.0L"),
        "head bolt torque?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is False
    assert "engine variant mismatch" in out.reason.lower()
    ollama.chat.assert_not_called()


def test_relevance_grader_passes_through_when_chunk_variant_is_null():
    """A chunk with no variant tag (e.g. maintenance schedule) reaches the LLM grader."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "general maintenance applies"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Oil change every 10k miles", engine_variant=None),
        "how often to change oil?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is True


def test_relevance_grader_passes_through_when_chunk_variant_is_both():
    """Spec convention: 'both' applies to either engine."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "applies to both"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Spark plug torque 30 Nm", engine_variant="both"),
        "spark plug torque?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is True


def test_relevance_grader_normalizes_vehicle_engine_token():
    """Vehicle.engine = '4.2L V8 (BFM)' must match chunk.engine_variant = '4.2L'."""
    ollama = MagicMock(spec=OllamaService)
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Head bolt torque 95 Nm", engine_variant="6.0L"),
        "head bolt torque?",
        _vehicle("4.2L V8 (BFM)"),
    )
    # Vehicle is 4.2L, chunk is 6.0L → still hard-reject.
    assert out.relevant is False


def test_relevance_grader_fails_open_on_malformed_json():
    """Spec: bad grader output → assume relevant, let groundedness catch it."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ['not json at all', 'still not json']
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("anything"), "q", _vehicle())
    assert out.relevant is True
    assert "malformed" in out.reason.lower()


def test_relevance_grader_retries_once_on_malformed_then_accepts_valid_retry():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = [
        'broken',
        '{"relevant": false, "reason": "wrong topic"}',
    ]
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("anything"), "q", _vehicle())
    assert out.relevant is False
    assert ollama.chat.call_count == 2
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_rag/test_grader.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement RelevanceGrader (and GroundednessGrader stub)**

Create `app/rag/grader.py`:

```python
# app/rag/grader.py
"""LLM graders for the agentic loop.

Both graders use a small fast model (gemma4:e4b) and structured JSON output.
Failure semantics differ:
  - RelevanceGrader fails OPEN: malformed output -> assume relevant. Better
    to send a candidate to generation than to lose it; groundedness catches
    bad answers.
  - GroundednessGrader fails CLOSED: malformed output -> treat as not
    grounded. Better to trigger a regeneration than to ship a fabrication.
"""
import json
import re
from dataclasses import dataclass

from app.models.document_chunk import DocumentChunk
from app.models.vehicle import Vehicle
from app.rag.loop_state import GradingResult
from app.services.ollama_service import OllamaService


_VARIANT_TOKEN = re.compile(r"\b(4\.2L|6\.0L|5\.2L|W12)\b", re.IGNORECASE)


@dataclass
class GroundednessResult:
    grounded: bool
    unsupported_claims: list[str]
    reason: str


# --- RelevanceGrader -----------------------------------------------------------


class RelevanceGrader:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def grade(
        self,
        chunk: DocumentChunk,
        question: str,
        vehicle: Vehicle,
    ) -> GradingResult:
        # Hard side of Q6: if chunk has a tagged variant and vehicle's engine
        # token implies a different variant, reject locally without an LLM call.
        vehicle_variant = _extract_variant(vehicle.engine)
        chunk_variant = (chunk.engine_variant or "").strip()
        if (
            chunk_variant
            and chunk_variant.lower() not in ("both",)
            and vehicle_variant is not None
            and chunk_variant != vehicle_variant
        ):
            return GradingResult(
                chunk=chunk,
                relevant=False,
                reason=f"engine variant mismatch: chunk={chunk_variant}, vehicle={vehicle_variant}",
            )

        # Soft side: ask the LLM.
        prompt = self._build_prompt(chunk, question, vehicle)
        for attempt in range(2):
            response = self._ollama.chat(
                [{"role": "user", "content": prompt}], self._model
            )
            parsed = _parse_json(response)
            if parsed is not None and "relevant" in parsed:
                return GradingResult(
                    chunk=chunk,
                    relevant=bool(parsed["relevant"]),
                    reason=str(parsed.get("reason", "")),
                )
            # Stricter retry prompt next round.
            prompt = self._strict_retry_prompt(chunk, question, vehicle)

        # Fail-open per spec.
        return GradingResult(
            chunk=chunk,
            relevant=True,
            reason="grader output malformed; failing open",
        )

    @staticmethod
    def _build_prompt(chunk: DocumentChunk, question: str, vehicle: Vehicle) -> str:
        return (
            "You judge whether a service-manual excerpt is relevant to a mechanic's question.\n\n"
            f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}\n"
            f"Chunk engine_variant tag: {chunk.engine_variant or 'none'}\n"
            f"Chunk section: {chunk.section_title or 'unknown'}\n\n"
            f"Question: {question}\n\n"
            "Excerpt:\n"
            f"{chunk.content[:1500]}\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"relevant": true | false, "reason": "<one sentence>"}\n'
            "An excerpt is relevant only if it directly answers the question for "
            f"this specific vehicle's engine ({vehicle.engine})."
        )

    @staticmethod
    def _strict_retry_prompt(chunk: DocumentChunk, question: str, vehicle: Vehicle) -> str:
        return (
            "Your previous response was not valid JSON. Reply with EXACTLY one line "
            "matching this format and nothing else:\n"
            '{"relevant": true, "reason": "..."}\n\n'
            f"Vehicle engine: {vehicle.engine}. Question: {question}\n"
            f"Excerpt: {chunk.content[:800]}"
        )


# --- GroundednessGrader --------------------------------------------------------


class GroundednessGrader:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def grade(
        self,
        answer: str,
        chunks: list[DocumentChunk],
    ) -> GroundednessResult:
        prompt = self._build_prompt(answer, chunks)
        for attempt in range(2):
            response = self._ollama.chat(
                [{"role": "user", "content": prompt}], self._model
            )
            parsed = _parse_json(response)
            if parsed is not None and "grounded" in parsed:
                claims = parsed.get("unsupported_claims", []) or []
                if not isinstance(claims, list):
                    claims = [str(claims)]
                return GroundednessResult(
                    grounded=bool(parsed["grounded"]),
                    unsupported_claims=[str(c) for c in claims],
                    reason=str(parsed.get("reason", "")),
                )
            prompt = self._strict_retry_prompt(answer)

        # Fail-closed per spec.
        return GroundednessResult(
            grounded=False,
            unsupported_claims=[],
            reason="grader output malformed; failing closed",
        )

    @staticmethod
    def _build_prompt(answer: str, chunks: list[DocumentChunk]) -> str:
        excerpts = "\n\n".join(
            f"[{i + 1}] {c.content[:800]}" for i, c in enumerate(chunks)
        )
        return (
            "You verify that an answer is supported by service-manual excerpts.\n\n"
            "Excerpts:\n"
            f"{excerpts}\n\n"
            f"Answer to verify:\n{answer}\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"grounded": true | false, "unsupported_claims": ["..."], "reason": "<one sentence>"}\n'
            "An answer is grounded only if every factual claim in it is directly "
            "supported by at least one excerpt. Unsupported_claims lists each "
            "claim in the answer that is not supported, or empty if grounded."
        )

    @staticmethod
    def _strict_retry_prompt(answer: str) -> str:
        return (
            "Your previous response was not valid JSON. Reply with EXACTLY one line:\n"
            '{"grounded": true, "unsupported_claims": [], "reason": "..."}\n\n'
            f"Answer to verify: {answer[:1500]}"
        )


# --- Helpers -------------------------------------------------------------------


def _extract_variant(engine_field: str) -> str | None:
    """Pull a canonical variant token (4.2L, 6.0L, etc.) out of free-form vehicle.engine."""
    if not engine_field:
        return None
    match = _VARIANT_TOKEN.search(engine_field)
    if not match:
        return None
    raw = match.group(1).lower()
    return {"4.2l": "4.2L", "6.0l": "6.0L", "5.2l": "5.2L", "w12": "W12"}[raw]


def _parse_json(text: str) -> dict | None:
    """Best-effort: extract the first JSON object from free-form LLM output."""
    if not text:
        return None
    # Direct parse first.
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Pull the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_rag/test_grader.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag/grader.py tests/test_rag/test_grader.py
git commit -m "feat: add RelevanceGrader with engine-variant hard reject"
```

---

## Task 4: GroundednessGrader

The class is already in `app/rag/grader.py` from Task 3. We only need to write the tests.

**Files:**
- Modify: `tests/test_rag/test_grader.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rag/test_grader.py`:

```python
# --- GroundednessGrader --------------------------------------------------------

def test_groundedness_grader_returns_grounded_true_with_empty_claims():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": true, "unsupported_claims": [], "reason": "all supported"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer text", [_chunk("supporting excerpt")])
    assert out.grounded is True
    assert out.unsupported_claims == []


def test_groundedness_grader_returns_unsupported_claims_when_not_grounded():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": false, "unsupported_claims": ["50 Nm spec not in excerpts"], '
        '"reason": "fabricated torque"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer", [_chunk("excerpt")])
    assert out.grounded is False
    assert out.unsupported_claims == ["50 Nm spec not in excerpts"]


def test_groundedness_grader_fails_closed_on_malformed_json():
    """Spec: bad output → treat as not grounded so the loop retries."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ['nope', 'still nope']
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer", [_chunk("excerpt")])
    assert out.grounded is False
    assert "malformed" in out.reason.lower()


def test_groundedness_grader_coerces_non_list_claims():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": false, "unsupported_claims": "single string claim", "reason": "x"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("a", [_chunk("c")])
    assert out.unsupported_claims == ["single string claim"]
```

- [ ] **Step 2: Run — expect pass**

Run: `uv run pytest tests/test_rag/test_grader.py -v`
Expected: 11 PASS total.

- [ ] **Step 3: Commit**

```bash
git add tests/test_rag/test_grader.py
git commit -m "test: groundedness grader passes/fails and fail-closed semantics"
```

---

## Task 5: QueryRewriter

**Files:**
- Create: `app/rag/query_rewriter.py`
- Create: `tests/test_rag/test_query_rewriter.py`

`QueryRewriter.rewrite(original_question, vehicle, prior_failure_reasons)` returns `{rewritten_query, rationale}`. Crucially: it conditions on the *original* question, never on the previous rewrite — prevents drift.

- [ ] **Step 1: Write failing tests**

Create `tests/test_rag/test_query_rewriter.py`:

```python
# tests/test_rag/test_query_rewriter.py
from unittest.mock import MagicMock

from app.models.vehicle import Vehicle
from app.rag.query_rewriter import QueryRewriter, RewriteResult
from app.services.ollama_service import OllamaService


def _vehicle() -> Vehicle:
    return Vehicle(year=2006, make="Audi", model="A8", engine="4.2L V8")


def test_rewriter_returns_rewritten_query_and_rationale():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"rewritten_query": "cylinder head bolt torque sequence 4.2L BFM V8", '
        '"rationale": "added engine code"}'
    )
    rewriter = QueryRewriter(ollama, model="m")
    out = rewriter.rewrite(
        original_question="what is the head bolt torque?",
        vehicle=_vehicle(),
        prior_failure_reasons=["all chunks rejected as engine-variant mismatch"],
    )
    assert isinstance(out, RewriteResult)
    assert "BFM" in out.rewritten_query
    assert out.rationale == "added engine code"


def test_rewriter_prompt_uses_original_question_not_previous_rewrite():
    """Spec: rewriter conditions on the immutable original question."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"rewritten_query": "x", "rationale": "y"}'
    )
    rewriter = QueryRewriter(ollama, model="m")
    rewriter.rewrite(
        original_question="ORIGINAL_Q",
        vehicle=_vehicle(),
        prior_failure_reasons=["a", "b"],
    )
    sent = ollama.chat.call_args.args[0][0]["content"]
    assert "ORIGINAL_Q" in sent
    assert "a" in sent and "b" in sent


def test_rewriter_falls_back_to_original_question_on_malformed_output():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "not json"
    rewriter = QueryRewriter(ollama, model="m")
    out = rewriter.rewrite(
        original_question="head bolt torque?",
        vehicle=_vehicle(),
        prior_failure_reasons=[],
    )
    assert out.rewritten_query == "head bolt torque?"
    assert "malformed" in out.rationale.lower()
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_rag/test_query_rewriter.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement QueryRewriter**

Create `app/rag/query_rewriter.py`:

```python
# app/rag/query_rewriter.py
"""LLM-driven query rewriter for the agentic loop.

Conditions on the IMMUTABLE original question plus a list of prior failure
reasons; never on the previous rewrite. This is a deliberate design choice
from the spec to prevent drift across iterations.
"""
from dataclasses import dataclass

from app.models.vehicle import Vehicle
from app.rag.grader import _parse_json  # reuse the helper
from app.services.ollama_service import OllamaService


@dataclass
class RewriteResult:
    rewritten_query: str
    rationale: str


class QueryRewriter:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def rewrite(
        self,
        original_question: str,
        vehicle: Vehicle,
        prior_failure_reasons: list[str],
    ) -> RewriteResult:
        reasons_text = "\n".join(f"- {r}" for r in prior_failure_reasons) or "- (none)"
        prompt = (
            "You rewrite a mechanic's question to retrieve better service-manual excerpts.\n\n"
            f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}\n\n"
            f"Original question:\n{original_question}\n\n"
            "Why the previous retrieval failed:\n"
            f"{reasons_text}\n\n"
            "Rewrite the question to be more specific to this vehicle and engine. "
            "Add manufacturer code, system names, or technical synonyms that appear in OEM manuals. "
            "Do NOT invent specifications. Stay tied to the original question's intent.\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"rewritten_query": "...", "rationale": "<one sentence>"}'
        )
        response = self._ollama.chat([{"role": "user", "content": prompt}], self._model)
        parsed = _parse_json(response)
        if parsed and "rewritten_query" in parsed:
            return RewriteResult(
                rewritten_query=str(parsed["rewritten_query"]),
                rationale=str(parsed.get("rationale", "")),
            )
        return RewriteResult(
            rewritten_query=original_question,
            rationale="rewriter output malformed; reusing original question",
        )
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_rag/test_query_rewriter.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag/query_rewriter.py tests/test_rag/test_query_rewriter.py
git commit -m "feat: add QueryRewriter conditioned on the original question"
```

---

## Task 6: Verbose console helpers

**Files:**
- Modify: `app/utils/console.py`

The spec's verbose UX shows every state transition with retrieval counts, rejection breakdown, optional rewrite line, generation marker, and groundedness check.

- [ ] **Step 1: Add helpers**

Append to `app/utils/console.py`:

```python
from app.rag.loop_state import LoopTraceEntry  # type-only is fine; circular avoided


def print_loop_step_retrieval(entry: LoopTraceEntry, max_iterations: int) -> None:
    iter_label = f"[{entry.iteration + 1}/{max_iterations + 1}]"
    quoted = f'"{entry.query}"'
    console.print(f"[bold cyan]{iter_label}[/bold cyan] Retrieving for {quoted}")
    console.print(
        f"      Hybrid: {entry.candidate_count} → reranked: {entry.reranked_count} "
        f"→ graded: {entry.relevant_count} relevant"
    )
    if entry.rejected_reasons:
        breakdown = ", ".join(
            f"{count} {reason}" for reason, count in entry.rejected_reasons.items()
        )
        rejected = sum(entry.rejected_reasons.values())
        console.print(f"      [dim]({rejected} rejected: {breakdown})[/dim]")


def print_loop_step_rewrite(entry: LoopTraceEntry) -> None:
    if entry.rewritten_query:
        console.print(f"[yellow]↻[/yellow] Query rewritten: \"{entry.rewritten_query}\"")
        if entry.rewrite_rationale:
            console.print(f"  [dim]{entry.rewrite_rationale}[/dim]")


def print_loop_step_generation(chunk_count: int, model: str) -> None:
    console.print(f"[cyan]✎[/cyan] Generating answer with {chunk_count} chunks ([dim]{model}[/dim])")


def print_loop_step_groundedness(passed: bool, unsupported: list[str] | None) -> None:
    if passed:
        console.print("[green]✓[/green] Groundedness check: PASS")
    else:
        console.print("[red]✗[/red] Groundedness check: FAIL")
        if unsupported:
            for claim in unsupported:
                console.print(f"  [red]·[/red] [dim]{claim}[/dim]")


def print_loop_refusal(searched_queries: int, total_examined: int, breakdown: dict[str, int]) -> None:
    console.print()
    console.print("[bold red]✗[/bold red] Could not answer from manuals.")
    console.print(f"  Searched {searched_queries} query variant(s); examined {total_examined} chunks.")
    if breakdown:
        for reason, count in breakdown.items():
            console.print(f"  · {count} {reason}")
    console.print()
```

- [ ] **Step 2: Smoke test imports**

Run: `uv run python -c "from app.utils.console import print_loop_step_retrieval, print_loop_step_rewrite, print_loop_step_generation, print_loop_step_groundedness, print_loop_refusal; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/utils/console.py
git commit -m "feat: add verbose console helpers for the agentic loop"
```

---

## Task 7: AgenticChatService — the bounded state machine

**Files:**
- Create: `app/services/agentic_chat_service.py`
- Create: `tests/test_services/test_agentic_chat_service.py`
- Modify: `app/rag/prompt_builder.py` (simplify the system prompt — variant warnings now handled by grader)

The state machine: at most `max_iterations + 1` retrieval passes (default 3 = initial + 2 rewrites). Per iteration:
1. Hybrid retrieve, excluding rejected ids.
2. Rerank to top-K.
3. Grade each chunk (parallel-ish — sequentially is fine for the small N).
4. If ≥1 relevant → generate → grade groundedness.
5. If groundedness fails or 0 relevant → rewrite query (unless we've hit MAX) and loop.
6. On MAX exhaustion → return structured refusal.

The service persists user + assistant messages and the loop trace (as JSON) into `chat_messages.sources_json`. (We extend the schema slightly: `sources_json` now also embeds the trace for transparency.)

- [ ] **Step 1: Simplify the prompt builder system prompt**

Replace `app/rag/prompt_builder.py`:

```python
# app/rag/prompt_builder.py
"""Build the assistant message list for Ollama /api/chat in the agentic flow.

The relevance grader has already filtered out engine-variant mismatches and
off-topic chunks before these messages are built — so the system prompt no
longer needs to lecture the LLM about engine variant filtering. It can focus
on grounding and citation.
"""
from app.models.chat_message import ChatMessage
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.vehicle import Vehicle


def build_system_prompt(vehicle: Vehicle) -> str:
    return (
        "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance.\n\n"
        f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}.\n\n"
        "Rules:\n"
        "- Answer ONLY using the manual excerpts provided below.\n"
        "- Never invent torque specs, fluid types, measurements, or procedures.\n"
        "- If the answer is not in the provided context, say: "
        "\"I could not find this in the available manuals.\"\n"
        "- Keep answers concise and mechanic-friendly.\n"
        "- Always cite your sources at the end of your answer.\n\n"
        "Answer format:\n"
        "Answer: <direct answer>\n\n"
        "Sources:\n"
        "- <filename>, page <number>"
    )


def build_messages(
    job: Job,
    vehicle: Vehicle,
    recent_messages: list[ChatMessage],
    chunks: list[DocumentChunk],
    question: str,
    document_map: dict[int, str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt(vehicle)}]
    messages.append({"role": "system", "content": f"Current job: {job.title}"})

    context_parts = []
    for i, chunk in enumerate(chunks, start=1):
        page_label = f"page {chunk.page_number}" if chunk.page_number is not None else "page unknown"
        filename = document_map.get(chunk.document_id, f"document_{chunk.document_id}")
        section_line = f"Section: {chunk.section_title}\n" if chunk.section_title else ""
        summary_line = f"Summary: {chunk.context_summary}\n" if chunk.context_summary else ""
        context_parts.append(f"[{i}] {filename}, {page_label}:\n{section_line}{summary_line}{chunk.content}")
    messages.append({"role": "system", "content": "Manual excerpts:\n\n" + "\n\n".join(context_parts)})

    for msg in recent_messages:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": question})
    return messages
```

Note the signature change: `chunks` is now `list[DocumentChunk]` (no scores), since the grader has already filtered. Update tests in `tests/test_rag/test_prompt_builder.py` accordingly:

- [ ] **Step 2: Update prompt builder tests for new signature**

Read `tests/test_rag/test_prompt_builder.py`. The fixture currently passes `list[tuple[DocumentChunk, float]]`. Update each `build_messages(..., chunks=...)` call to pass `[chunk_obj1, chunk_obj2]` instead of `[(chunk_obj1, 0.9), ...]`. Drop the score-related assertions.

Run: `uv run pytest tests/test_rag/test_prompt_builder.py -v`
Expected: green after the test edits.

- [ ] **Step 3: Write the AgenticChatService tests**

Create `tests/test_services/test_agentic_chat_service.py`:

```python
# tests/test_services/test_agentic_chat_service.py
import json
import pytest
from unittest.mock import MagicMock

from app.models.document_chunk import DocumentChunk
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.rag.grader import (
    GroundednessGrader, GroundednessResult, RelevanceGrader,
)
from app.rag.loop_state import GradingResult
from app.rag.query_rewriter import QueryRewriter, RewriteResult
from app.services.agentic_chat_service import AgenticChatService
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.ollama_service import OllamaService
from app.services.reranker import Reranker


@pytest.fixture
def job_and_vehicle(db_session):
    vehicle = VehicleRepository(db_session).create(year=2006, make="Audi", model="A8", engine="4.2L V8")
    db_session.flush()
    job = JobRepository(db_session).create(vehicle_id=vehicle.id, title="head bolt torque check")
    db_session.flush()
    return job, vehicle


def _make_chunk(content: str, page: int = 1, doc_id: int = 1) -> DocumentChunk:
    c = DocumentChunk(document_id=doc_id, chunk_index=0, content=content, page_number=page)
    c.id = page  # quick & dirty unique id for tests; Mock signal only
    return c


def _make_service(db_session, **overrides):
    retrieval = overrides.get("retrieval") or MagicMock(spec=HybridRetrievalService)
    reranker = overrides.get("reranker") or MagicMock(spec=Reranker)
    relevance = overrides.get("relevance") or MagicMock(spec=RelevanceGrader)
    groundedness = overrides.get("groundedness") or MagicMock(spec=GroundednessGrader)
    rewriter = overrides.get("rewriter") or MagicMock(spec=QueryRewriter)
    ollama = overrides.get("ollama") or MagicMock(spec=OllamaService)

    return AgenticChatService(
        chat_repo=ChatRepository(db_session),
        job_repo=JobRepository(db_session),
        vehicle_repo=VehicleRepository(db_session),
        doc_repo=overrides.get("doc_repo") or MagicMock(spec=DocumentRepository),
        retrieval_service=retrieval,
        reranker=reranker,
        relevance_grader=relevance,
        groundedness_grader=groundedness,
        query_rewriter=rewriter,
        ollama_service=ollama,
        chat_model="gemma4:26b",
        recent_messages_limit=6,
        max_iterations=2,
        rerank_top_k=10,
        verbose=False,
    )


def test_happy_path_first_iteration_succeeds(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    chunk = _make_chunk("Cylinder head bolt torque is 129 Nm")

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.return_value = [(chunk, 0.5)]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.return_value = [(chunk, 0.9)]
    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.return_value = GradingResult(chunk=chunk, relevant=True, reason="ok")
    groundedness = MagicMock(spec=GroundednessGrader)
    groundedness.grade.return_value = GroundednessResult(grounded=True, unsupported_claims=[], reason="ok")

    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "Answer: 129 Nm.\n\nSources:\n- manual.pdf, page 1"

    doc_repo = MagicMock(spec=DocumentRepository)
    doc = MagicMock()
    doc.file_name = "manual.pdf"
    doc_repo.get_by_id.return_value = doc

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker,
        relevance=relevance, groundedness=groundedness, ollama=ollama,
        doc_repo=doc_repo,
    )

    result = svc.ask(job_id=job.id, question="head bolt torque?")
    db_session.flush()

    assert "129 Nm" in result.answer
    assert len(result.sources) == 1
    assert result.sources[0]["filename"] == "manual.pdf"
    assert len(result.trace) == 1
    assert result.trace[0].relevant_count == 1
    assert retrieval.retrieve.call_count == 1
    # User + assistant messages persisted.
    msgs = ChatRepository(db_session).list_by_job(job.id)
    assert len(msgs) == 2


def test_no_relevant_chunks_triggers_rewrite_then_succeeds(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    bad_chunk = _make_chunk("Wrong topic", page=10)
    good_chunk = _make_chunk("Head bolt 129 Nm", page=11)

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.side_effect = [[(bad_chunk, 0.1)], [(good_chunk, 0.9)]]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.side_effect = [[(bad_chunk, 0.1)], [(good_chunk, 0.9)]]

    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.side_effect = [
        GradingResult(chunk=bad_chunk, relevant=False, reason="off-topic"),
        GradingResult(chunk=good_chunk, relevant=True, reason="ok"),
    ]
    groundedness = MagicMock(spec=GroundednessGrader)
    groundedness.grade.return_value = GroundednessResult(grounded=True, unsupported_claims=[], reason="ok")
    rewriter = MagicMock(spec=QueryRewriter)
    rewriter.rewrite.return_value = RewriteResult(
        rewritten_query="cylinder head torque 4.2L BFM",
        rationale="added engine code",
    )
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "Answer: 129 Nm.\n\nSources:\n- m.pdf, page 11"

    doc_repo = MagicMock(spec=DocumentRepository)
    doc = MagicMock(); doc.file_name = "m.pdf"
    doc_repo.get_by_id.return_value = doc

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, rewriter=rewriter, ollama=ollama, doc_repo=doc_repo,
    )

    result = svc.ask(job_id=job.id, question="head bolt torque?")
    db_session.flush()

    assert retrieval.retrieve.call_count == 2
    # First call: original question, no excludes.
    first_call = retrieval.retrieve.call_args_list[0]
    assert first_call.kwargs["query"] == "head bolt torque?" or first_call.args[0] == "head bolt torque?"
    # Second call: rewritten query, excludes bad_chunk.
    second_call = retrieval.retrieve.call_args_list[1]
    assert "BFM" in (second_call.kwargs.get("query") or second_call.args[0])
    assert bad_chunk.id in (second_call.kwargs.get("exclude_chunk_ids") or frozenset())

    assert "129 Nm" in result.answer
    assert len(result.trace) == 2
    rewriter.rewrite.assert_called_once()
    # Rewriter conditioned on the ORIGINAL question, not the previous attempt.
    args = rewriter.rewrite.call_args
    assert args.kwargs.get("original_question") == "head bolt torque?" \
        or args.args[0] == "head bolt torque?"


def test_groundedness_fail_triggers_rewrite(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    chunk1 = _make_chunk("text1", page=1)
    chunk2 = _make_chunk("text2", page=2)

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.side_effect = [[(chunk1, 0.5)], [(chunk2, 0.5)]]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.side_effect = [[(chunk1, 0.5)], [(chunk2, 0.5)]]
    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.side_effect = [
        GradingResult(chunk=chunk1, relevant=True, reason="ok"),
        GradingResult(chunk=chunk2, relevant=True, reason="ok"),
    ]
    groundedness = MagicMock(spec=GroundednessGrader)
    groundedness.grade.side_effect = [
        GroundednessResult(grounded=False, unsupported_claims=["fabricated 50 Nm"], reason="fail"),
        GroundednessResult(grounded=True, unsupported_claims=[], reason="ok"),
    ]
    rewriter = MagicMock(spec=QueryRewriter)
    rewriter.rewrite.return_value = RewriteResult(rewritten_query="rewrite", rationale="r")
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ["bad answer", "good answer"]
    doc_repo = MagicMock(spec=DocumentRepository)
    doc_repo.get_by_id.return_value = MagicMock(file_name="m.pdf")

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, rewriter=rewriter, ollama=ollama, doc_repo=doc_repo,
    )
    result = svc.ask(job_id=job.id, question="q")
    db_session.flush()

    assert "good answer" in result.answer
    assert len(result.trace) == 2


def test_max_iterations_returns_structured_refusal(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    chunk = _make_chunk("nope", page=1)

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.return_value = [(chunk, 0.1)]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.return_value = [(chunk, 0.1)]
    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.return_value = GradingResult(
        chunk=chunk, relevant=False, reason="engine variant mismatch: chunk=6.0L, vehicle=4.2L",
    )
    groundedness = MagicMock(spec=GroundednessGrader)
    rewriter = MagicMock(spec=QueryRewriter)
    rewriter.rewrite.return_value = RewriteResult(rewritten_query="x", rationale="r")

    ollama = MagicMock(spec=OllamaService)

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, rewriter=rewriter, ollama=ollama,
    )
    result = svc.ask(job_id=job.id, question="q")
    db_session.flush()

    # 3 retrieval passes (initial + 2 rewrites), no answer generated, refusal returned.
    assert retrieval.retrieve.call_count == 3
    assert ollama.chat.call_count == 0
    assert result.sources == []
    assert "could not find" in result.answer.lower() or "couldn't find" in result.answer.lower()
    # Trace records all 3 iterations.
    assert len(result.trace) == 3
    # Refusal includes rejected-reason breakdown.
    assert "engine variant" in result.answer.lower()


def test_rejected_chunk_ids_accumulate_across_iterations(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    c1 = _make_chunk("a", page=1)
    c2 = _make_chunk("b", page=2)
    c3 = _make_chunk("c", page=3)

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.side_effect = [
        [(c1, 0.5)],
        [(c2, 0.5)],
        [(c3, 0.5)],
    ]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.side_effect = [
        [(c1, 0.5)],
        [(c2, 0.5)],
        [(c3, 0.5)],
    ]
    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.side_effect = [
        GradingResult(chunk=c1, relevant=False, reason="off-topic"),
        GradingResult(chunk=c2, relevant=False, reason="off-topic"),
        GradingResult(chunk=c3, relevant=False, reason="off-topic"),
    ]
    groundedness = MagicMock(spec=GroundednessGrader)
    rewriter = MagicMock(spec=QueryRewriter)
    rewriter.rewrite.return_value = RewriteResult(rewritten_query="rw", rationale="r")

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, rewriter=rewriter,
    )
    svc.ask(job_id=job.id, question="q")
    db_session.flush()

    # 3rd call should exclude {c1.id, c2.id}; 2nd should exclude {c1.id}.
    second_excludes = retrieval.retrieve.call_args_list[1].kwargs.get("exclude_chunk_ids") or frozenset()
    third_excludes = retrieval.retrieve.call_args_list[2].kwargs.get("exclude_chunk_ids") or frozenset()
    assert c1.id in second_excludes
    assert c1.id in third_excludes and c2.id in third_excludes


def test_persists_loop_trace_in_sources_json(db_session, job_and_vehicle):
    job, vehicle = job_and_vehicle
    chunk = _make_chunk("Head bolt 129 Nm", page=11)

    retrieval = MagicMock(spec=HybridRetrievalService)
    retrieval.retrieve.return_value = [(chunk, 0.9)]
    reranker = MagicMock(spec=Reranker)
    reranker.rerank.return_value = [(chunk, 0.9)]
    relevance = MagicMock(spec=RelevanceGrader)
    relevance.grade.return_value = GradingResult(chunk=chunk, relevant=True, reason="ok")
    groundedness = MagicMock(spec=GroundednessGrader)
    groundedness.grade.return_value = GroundednessResult(grounded=True, unsupported_claims=[], reason="ok")
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "Answer."
    doc_repo = MagicMock(spec=DocumentRepository)
    doc_repo.get_by_id.return_value = MagicMock(file_name="m.pdf")

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, ollama=ollama, doc_repo=doc_repo,
    )
    svc.ask(job_id=job.id, question="q")
    db_session.flush()

    msgs = ChatRepository(db_session).list_by_job(job.id)
    assistant_msg = msgs[-1]
    payload = json.loads(assistant_msg.sources_json)
    assert "sources" in payload
    assert "trace" in payload
    assert len(payload["trace"]) == 1


def test_raises_value_error_when_job_missing(db_session):
    svc = _make_service(db_session)
    with pytest.raises(ValueError, match="Job 999 not found"):
        svc.ask(job_id=999, question="q")
```

- [ ] **Step 4: Run — expect import failure**

Run: `uv run pytest tests/test_services/test_agentic_chat_service.py -v`
Expected: FAIL — `AgenticChatService` does not exist.

- [ ] **Step 5: Implement AgenticChatService**

Create `app/services/agentic_chat_service.py`:

```python
# app/services/agentic_chat_service.py
"""Bounded agentic loop: retrieve → grade → generate → ground → maybe rewrite.

The loop is a deterministic state machine with at most max_iterations + 1
retrieval passes. Loop trace is persisted alongside sources so the user can
audit retries.
"""
import json
from collections import Counter
from dataclasses import dataclass

from app.models.document_chunk import DocumentChunk
from app.rag.grader import GroundednessGrader, RelevanceGrader
from app.rag.loop_state import GradingResult, LoopState, LoopTraceEntry
from app.rag.prompt_builder import build_messages
from app.rag.query_rewriter import QueryRewriter
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.ollama_service import OllamaService
from app.services.reranker import Reranker
from app.utils.console import (
    print_loop_refusal,
    print_loop_step_generation,
    print_loop_step_groundedness,
    print_loop_step_retrieval,
    print_loop_step_rewrite,
)


@dataclass
class AskResult:
    answer: str
    sources: list[dict]
    trace: list[LoopTraceEntry]


class AgenticChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        job_repo: JobRepository,
        vehicle_repo: VehicleRepository,
        doc_repo: DocumentRepository,
        retrieval_service: HybridRetrievalService,
        reranker: Reranker,
        relevance_grader: RelevanceGrader,
        groundedness_grader: GroundednessGrader,
        query_rewriter: QueryRewriter,
        ollama_service: OllamaService,
        chat_model: str,
        recent_messages_limit: int = 6,
        max_iterations: int = 2,
        rerank_top_k: int = 10,
        verbose: bool = True,
    ) -> None:
        self._chat_repo = chat_repo
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo
        self._doc_repo = doc_repo
        self._retrieval = retrieval_service
        self._reranker = reranker
        self._relevance = relevance_grader
        self._groundedness = groundedness_grader
        self._rewriter = query_rewriter
        self._ollama = ollama_service
        self._chat_model = chat_model
        self._recent_messages_limit = recent_messages_limit
        self._max_iterations = max_iterations
        self._rerank_top_k = rerank_top_k
        self._verbose = verbose

    def ask(self, job_id: int, question: str) -> AskResult:
        job = self._job_repo.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        vehicle = self._vehicle_repo.get_by_id(job.vehicle_id)
        if vehicle is None:
            raise ValueError(f"Vehicle {job.vehicle_id} not found for job {job_id}")

        recent = self._chat_repo.list_by_job(job_id, limit=self._recent_messages_limit)
        self._chat_repo.create(job_id=job_id, role="user", content=question)

        state = LoopState(original_question=question, current_query=question)

        for iteration in range(self._max_iterations + 1):
            state.iteration = iteration
            entry = self._run_iteration(state, vehicle)
            state.trace.append(entry)

            if entry.relevant_count == 0:
                # Will rewrite (or refuse) below.
                if iteration < self._max_iterations:
                    self._rewrite_into_state(state, vehicle, "no relevant chunks")
                    continue
                break

            # We have relevant chunks → generate.
            relevant_chunks = self._collect_relevant_chunks(state.trace[-1])
            answer = self._generate_answer(job, vehicle, recent, relevant_chunks, state.original_question)
            entry.generated_answer = answer

            grounded = self._groundedness.grade(answer, relevant_chunks)
            entry.groundedness_pass = grounded.grounded
            entry.groundedness_unsupported = grounded.unsupported_claims
            if self._verbose:
                print_loop_step_groundedness(grounded.grounded, grounded.unsupported_claims)

            if grounded.grounded:
                return self._finalize_success(
                    job_id, answer, relevant_chunks, state.trace,
                )

            # Groundedness failed: rewrite if we have iterations left.
            if iteration < self._max_iterations:
                self._rewrite_into_state(
                    state, vehicle,
                    "groundedness fail: " + ", ".join(grounded.unsupported_claims) or grounded.reason,
                )
                continue
            break

        return self._finalize_refusal(job_id, state)

    # --- Internal steps ----------------------------------------------------

    def _run_iteration(self, state: LoopState, vehicle) -> LoopTraceEntry:
        # 1. Hybrid retrieve.
        candidates = self._retrieval.retrieve(
            query=state.current_query,
            vehicle_id=vehicle.id,
            exclude_chunk_ids=frozenset(state.rejected_chunk_ids),
        )
        candidate_count = len(candidates)
        if candidate_count == 0:
            entry = LoopTraceEntry(
                iteration=state.iteration,
                query=state.current_query,
                candidate_count=0,
                reranked_count=0,
                relevant_count=0,
                rejected_reasons={},
            )
            entry._relevant_chunks = []  # internal: see _collect_relevant_chunks
            if self._verbose:
                print_loop_step_retrieval(entry, self._max_iterations)
            return entry

        # 2. Rerank.
        reranked = self._reranker.rerank(
            query=state.current_query,
            candidates=[c for c, _ in candidates],
            top_k=self._rerank_top_k,
        )

        # 3. Grade each.
        results: list[GradingResult] = [
            self._relevance.grade(chunk=c, question=state.original_question, vehicle=vehicle)
            for c, _ in reranked
        ]
        relevant = [r for r in results if r.relevant]
        rejected = [r for r in results if not r.relevant]

        # Track rejected ids for next iteration.
        state.rejected_chunk_ids.update(r.chunk.id for r in rejected if r.chunk.id is not None)

        rejected_reasons = self._summarise_reasons(rejected)
        entry = LoopTraceEntry(
            iteration=state.iteration,
            query=state.current_query,
            candidate_count=candidate_count,
            reranked_count=len(reranked),
            relevant_count=len(relevant),
            rejected_reasons=rejected_reasons,
        )
        entry._relevant_chunks = [r.chunk for r in relevant]  # internal stash
        if self._verbose:
            print_loop_step_retrieval(entry, self._max_iterations)
        return entry

    @staticmethod
    def _summarise_reasons(rejected: list[GradingResult]) -> dict[str, int]:
        """Group reasons into compact buckets for the trace."""
        buckets: Counter[str] = Counter()
        for r in rejected:
            reason = r.reason.lower()
            if "engine variant" in reason:
                buckets["engine variant mismatch"] += 1
            elif "off" in reason or "topic" in reason or "irrelev" in reason:
                buckets["off-topic"] += 1
            else:
                buckets["other"] += 1
        return dict(buckets)

    @staticmethod
    def _collect_relevant_chunks(entry: LoopTraceEntry) -> list[DocumentChunk]:
        return getattr(entry, "_relevant_chunks", [])

    def _rewrite_into_state(self, state: LoopState, vehicle, failure_reason: str) -> None:
        state.failure_reasons.append(failure_reason)
        result = self._rewriter.rewrite(
            original_question=state.original_question,
            vehicle=vehicle,
            prior_failure_reasons=state.failure_reasons,
        )
        state.current_query = result.rewritten_query
        # Annotate the just-finished trace entry with the rewrite for verbose output.
        last = state.trace[-1]
        last.rewritten_query = result.rewritten_query
        last.rewrite_rationale = result.rationale
        if self._verbose:
            print_loop_step_rewrite(last)

    def _generate_answer(self, job, vehicle, recent, chunks: list[DocumentChunk], question: str) -> str:
        if self._verbose:
            print_loop_step_generation(len(chunks), self._chat_model)
        document_map = self._build_document_map(chunks)
        messages = build_messages(job, vehicle, recent, chunks, question, document_map)
        return self._ollama.chat(messages, self._chat_model)

    def _build_document_map(self, chunks: list[DocumentChunk]) -> dict[int, str]:
        result: dict[int, str] = {}
        for c in chunks:
            if c.document_id in result:
                continue
            doc = self._doc_repo.get_by_id(c.document_id)
            if doc:
                result[c.document_id] = doc.file_name
        return result

    def _finalize_success(
        self,
        job_id: int,
        answer: str,
        chunks: list[DocumentChunk],
        trace: list[LoopTraceEntry],
    ) -> AskResult:
        document_map = self._build_document_map(chunks)
        sources = [
            {
                "filename": document_map.get(c.document_id, f"document_{c.document_id}"),
                "page": c.page_number,
            }
            for c in chunks
        ]
        payload = {"sources": sources, "trace": [_serialize_trace_entry(t) for t in trace]}
        self._chat_repo.create(
            job_id=job_id, role="assistant", content=answer,
            sources_json=json.dumps(payload),
        )
        return AskResult(answer=answer, sources=sources, trace=trace)

    def _finalize_refusal(self, job_id: int, state: LoopState) -> AskResult:
        breakdown: Counter[str] = Counter()
        total_examined = 0
        for entry in state.trace:
            total_examined += entry.candidate_count
            for reason, count in entry.rejected_reasons.items():
                breakdown[reason] += count

        breakdown_str = ", ".join(f"{count} {reason}" for reason, count in breakdown.items()) or "no chunks examined"
        answer = (
            f"I could not find that in the manuals for this vehicle. "
            f"Searched {len(state.trace)} query variant(s); "
            f"{total_examined} chunks examined ({breakdown_str})."
        )

        if self._verbose:
            print_loop_refusal(len(state.trace), total_examined, dict(breakdown))

        payload = {"sources": [], "trace": [_serialize_trace_entry(t) for t in state.trace]}
        self._chat_repo.create(
            job_id=job_id, role="assistant", content=answer,
            sources_json=json.dumps(payload),
        )
        return AskResult(answer=answer, sources=[], trace=state.trace)


def _serialize_trace_entry(entry: LoopTraceEntry) -> dict:
    """Plain-dict view for sources_json persistence."""
    return {
        "iteration": entry.iteration,
        "query": entry.query,
        "candidate_count": entry.candidate_count,
        "reranked_count": entry.reranked_count,
        "relevant_count": entry.relevant_count,
        "rejected_reasons": entry.rejected_reasons,
        "rewritten_query": entry.rewritten_query,
        "rewrite_rationale": entry.rewrite_rationale,
        "groundedness_pass": entry.groundedness_pass,
        "groundedness_unsupported": entry.groundedness_unsupported,
    }
```

- [ ] **Step 6: Run — expect pass**

Run: `uv run pytest tests/test_services/test_agentic_chat_service.py -v`
Expected: 7 PASS.

If any fail, the most common issues are:
- `_relevant_chunks` access via `_collect_relevant_chunks` — MagicMock `chunk` ids may not survive. Tests assign `c.id = page` to give chunks stable ids; ensure `_relevant_chunks` uses real chunk objects from the iteration (the helper above stashes them).
- Refusal text — must contain `"could not find"` (test assertion). The implementation already does.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add app/services/agentic_chat_service.py app/rag/prompt_builder.py
git add tests/test_services/test_agentic_chat_service.py tests/test_rag/test_prompt_builder.py
git commit -m "feat: add AgenticChatService with bounded retrieve-grade-rewrite loop"
```

---

## Task 8: CLI wiring + new config keys

**Files:**
- Modify: `app/cli.py`
- Modify: `app/config.py`

- [ ] **Step 1: Add max_loop_iterations and loop_verbose to Settings**

Edit `app/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "gemma4:26b"
    context_model: str = "gemma4:e4b"
    embed_model: str = "qwen3-embedding:4b"
    db_path: str = "./data/app.db"
    docs_dir: str = "./data/documents"
    chunk_size: int = 500
    chunk_overlap: int = 100
    recent_messages: int = 6
    vec_dim: int = 2560

    bm25_top_k: int = 30
    vector_top_k: int = 30
    rrf_k: int = 60
    rerank_top_k: int = 10
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Agentic loop (Plan 3)
    max_loop_iterations: int = 2
    loop_verbose: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 2: Wire AgenticChatService**

In `app/cli.py`, replace the stubbed `_make_chat_service`:

```python
def _make_chat_service(session):
    from app.repositories.vehicle_repository import VehicleRepository
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.job_repository import JobRepository
    from app.repositories.chat_repository import ChatRepository
    from app.rag.grader import GroundednessGrader, RelevanceGrader
    from app.rag.query_rewriter import QueryRewriter
    from app.services.agentic_chat_service import AgenticChatService
    from app.services.embedding_service import EmbeddingService
    from app.services.hybrid_retrieval_service import HybridRetrievalService
    from app.services.ollama_service import OllamaService
    from app.services.reranker import BgeReranker

    ollama_svc = OllamaService(settings.ollama_base_url)
    embedding_svc = EmbeddingService(ollama_svc, settings.embed_model)

    retrieval_svc = HybridRetrievalService(
        session=session,
        embedding_service=embedding_svc,
        bm25_top_k=settings.bm25_top_k,
        vector_top_k=settings.vector_top_k,
        rrf_k=settings.rrf_k,
        result_top_k=max(settings.bm25_top_k, settings.vector_top_k),
    )
    reranker = BgeReranker(model_name=settings.reranker_model)
    relevance = RelevanceGrader(ollama_svc, settings.context_model)
    groundedness = GroundednessGrader(ollama_svc, settings.context_model)
    rewriter = QueryRewriter(ollama_svc, settings.context_model)

    return AgenticChatService(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval_service=retrieval_svc,
        reranker=reranker,
        relevance_grader=relevance,
        groundedness_grader=groundedness,
        query_rewriter=rewriter,
        ollama_service=ollama_svc,
        chat_model=settings.chat_model,
        recent_messages_limit=settings.recent_messages,
        max_iterations=settings.max_loop_iterations,
        rerank_top_k=settings.rerank_top_k,
        verbose=settings.loop_verbose,
    )
```

- [ ] **Step 3: Update chat commands to use AskResult**

In `app/cli.py`, the existing `chat ask` and `chat start` commands unpack `(answer, sources)`. The new service returns `AskResult`. Update both:

```python
@chat_app.command("ask")
def chat_ask(job_id: int, question: str):
    """Ask a single question in a job context."""
    with get_session() as session:
        svc = _make_chat_service(session)
        try:
            result = svc.ask(job_id=job_id, question=question)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error: {e}")
            raise typer.Exit(1)
        print_answer(result.answer, result.sources)


@chat_app.command("start")
def chat_start(job_id: int):
    """Start an interactive chat session for a job."""
    with get_session() as session:
        job_svc = _make_job_service(session)
        try:
            job = job_svc.get_job(job_id)
            header = f"{job.title} (ID: {job.id})"
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)

    console.print(f"\n[bold cyan]Job:[/bold cyan] {header}")
    console.print("[dim]Type your question, or 'quit' to exit.[/dim]\n")

    while True:
        try:
            question = typer.prompt("You")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if question.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Session ended.[/dim]")
            break
        if not question.strip():
            continue

        with get_session() as session:
            svc = _make_chat_service(session)
            try:
                result = svc.ask(job_id=job_id, question=question)
            except Exception as e:
                print_error(f"Error: {e}")
                continue
            print_answer(result.answer, result.sources)
```

Note: removed the `console.status("Thinking...", spinner="dots")` wrapper because verbose mode prints loop steps as they happen — a spinner would clobber them. Quiet-mode fans can flip `loop_verbose=false` and re-add the spinner if desired.

- [ ] **Step 4: Smoke test**

Run: `uv run mechanic-sidekick --help`
Expected: shows `chat` subcommands.

Run: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add app/cli.py app/config.py
git commit -m "feat: wire AgenticChatService into chat CLI commands"
```

---

## Task 9: End-to-end smoke chat against real Ollama + reranker

**Goal:** Verify the agentic loop runs against real models on a real corpus.

- [ ] **Step 1: Ensure the corpus is ingested**

Skip if you ingested at least one PDF after Plan 1. Otherwise repeat Plan 1, Task 11.

- [ ] **Step 2: Create a job**

```bash
uv run mechanic-sidekick job add 1
```

At prompts: title `"head bolt torque"`, description (skip).

- [ ] **Step 3: Ask a question that should match cleanly**

```bash
uv run mechanic-sidekick chat ask 1 "What is the cylinder head bolt torque sequence?"
```

Expected verbose output:

```
[1/3] Retrieving for "What is the cylinder head bolt torque sequence?"
      Hybrid: 30 → reranked: 10 → graded: <N> relevant
✎ Generating answer with <N> chunks (gemma4:26b)
✓ Groundedness check: PASS

╭─ Answer ─...
│ Answer: <torque sequence text>
...

Sources:
 1. 15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf, page <N>
```

Tolerable variation: the loop may rewrite once if the first pass under-retrieves. Look for a sane answer with 4.2L sources, not a refusal.

- [ ] **Step 4: Ask a deliberate engine-variant trap**

```bash
uv run mechanic-sidekick chat ask 1 "What is the 6.0L cylinder head warpage limit?"
```

Expected: with the vehicle being `4.2L V8`, the 6.0L chunks should be rejected by the relevance grader. Output should include:

```
      (10 rejected: 10 engine variant mismatch)
↻ Query rewritten: "..."
```

Eventually a structured refusal:

```
✗ Could not answer from manuals.
  Searched 3 query variant(s); examined ~90 chunks.
  · ~30 engine variant mismatch
```

This proves the hard-side variant filter is working end-to-end.

- [ ] **Step 5: No commit**

Verification only.

---

## Self-Review Checklist (run before marking Plan 3 done)

- [ ] Spec section 4 — every transition covered? Retrieve → grade → generate → ground → rewrite → loop. State carried via `LoopState`. Trace returned to caller. Refusal path on exhaustion.
- [ ] Spec Q6 hybrid filter — soft (LLM grader) + hard (locally rejecting variant mismatch). Implemented in `RelevanceGrader.grade`.
- [ ] Spec malformed-output asymmetry: relevance fails open, groundedness fails closed. Tested in Task 3 + Task 4.
- [ ] Spec rewriter conditioning on the *original* question: enforced and tested in Task 5.
- [ ] Verbose UX matches spec format: `print_loop_step_*` helpers, called by the loop at every transition.
- [ ] No placeholders. Type names consistent: `RelevanceGrader.grade(chunk, question, vehicle) -> GradingResult`; `GroundednessGrader.grade(answer, chunks) -> GroundednessResult`; `QueryRewriter.rewrite(original_question, vehicle, prior_failure_reasons) -> RewriteResult`; `AgenticChatService.ask(job_id, question) -> AskResult` — all consistent.
- [ ] CLI removes `console.status("Thinking…")` so verbose output is visible. Acknowledged trade-off in Task 8 step 3.
- [ ] Configurable: `max_loop_iterations`, `loop_verbose`, `rerank_top_k`, all `bm25/vector_top_k`, `rrf_k` → all in `Settings`.
