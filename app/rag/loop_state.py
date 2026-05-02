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
