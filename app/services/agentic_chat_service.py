# app/services/agentic_chat_service.py
"""Bounded agentic loop: retrieve, grade, generate, ground, maybe rewrite.

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
            entry, relevant_chunks = self._run_iteration(state, vehicle)
            state.trace.append(entry)

            if entry.relevant_count == 0:
                if iteration < self._max_iterations:
                    self._rewrite_into_state(state, vehicle, "no relevant chunks")
                    continue
                break

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

            if iteration < self._max_iterations:
                detail = ", ".join(grounded.unsupported_claims) or grounded.reason
                self._rewrite_into_state(state, vehicle, f"groundedness fail: {detail}")
                continue
            break

        return self._finalize_refusal(job_id, state)

    def _run_iteration(
        self, state: LoopState, vehicle
    ) -> tuple[LoopTraceEntry, list[DocumentChunk]]:
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
            if self._verbose:
                print_loop_step_retrieval(entry, self._max_iterations)
            return entry, []

        reranked = self._reranker.rerank(
            query=state.current_query,
            candidates=[c for c, _ in candidates],
            top_k=self._rerank_top_k,
        )

        results: list[GradingResult] = [
            self._relevance.grade(chunk=c, question=state.original_question, vehicle=vehicle)
            for c, _ in reranked
        ]
        relevant = [r.chunk for r in results if r.relevant]
        rejected = [r for r in results if not r.relevant]

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
        if self._verbose:
            print_loop_step_retrieval(entry, self._max_iterations)
        return entry, relevant

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

    def _rewrite_into_state(self, state: LoopState, vehicle, failure_reason: str) -> None:
        state.failure_reasons.append(failure_reason)
        result = self._rewriter.rewrite(
            original_question=state.original_question,
            vehicle=vehicle,
            prior_failure_reasons=state.failure_reasons,
        )
        state.current_query = result.rewritten_query
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
