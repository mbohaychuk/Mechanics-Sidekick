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
    first_call = retrieval.retrieve.call_args_list[0]
    assert first_call.kwargs["query"] == "head bolt torque?" or first_call.args[0] == "head bolt torque?"
    second_call = retrieval.retrieve.call_args_list[1]
    assert "BFM" in (second_call.kwargs.get("query") or second_call.args[0])
    assert bad_chunk.id in (second_call.kwargs.get("exclude_chunk_ids") or frozenset())

    assert "129 Nm" in result.answer
    assert len(result.trace) == 2
    rewriter.rewrite.assert_called_once()
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

    assert retrieval.retrieve.call_count == 3
    assert ollama.chat.call_count == 0
    assert result.sources == []
    assert "could not find" in result.answer.lower() or "couldn't find" in result.answer.lower()
    assert len(result.trace) == 3
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


def test_groundedness_fail_without_claims_uses_reason_in_rewrite_failure(db_session, job_and_vehicle):
    """When grounded=False but unsupported_claims=[], the rewriter must hear the reason text."""
    job, _ = job_and_vehicle
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
        GroundednessResult(grounded=False, unsupported_claims=[], reason="answer contradicts context"),
        GroundednessResult(grounded=True, unsupported_claims=[], reason="ok"),
    ]
    rewriter = MagicMock(spec=QueryRewriter)
    rewriter.rewrite.return_value = RewriteResult(rewritten_query="rw", rationale="r")
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ["bad answer", "good answer"]
    doc_repo = MagicMock(spec=DocumentRepository)
    doc_repo.get_by_id.return_value = MagicMock(file_name="m.pdf")

    svc = _make_service(
        db_session, retrieval=retrieval, reranker=reranker, relevance=relevance,
        groundedness=groundedness, rewriter=rewriter, ollama=ollama, doc_repo=doc_repo,
    )
    svc.ask(job_id=job.id, question="q")
    db_session.flush()

    rewriter.rewrite.assert_called_once()
    failure_reasons = rewriter.rewrite.call_args.kwargs["prior_failure_reasons"]
    assert any("answer contradicts context" in r for r in failure_reasons)
