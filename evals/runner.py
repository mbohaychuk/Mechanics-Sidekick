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
from app.rag.grader import GroundednessGrader, RelevanceGrader
from app.rag.query_rewriter import QueryRewriter
from app.services.agentic_chat_service import AgenticChatService
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_retrieval_service import HybridRetrievalService
from app.services.ollama_service import OllamaService
from app.services.reranker import BgeReranker
from evals.grader import GraderResult, LlmJudgeGrader, SubstringAnyGrader
from evals.seed import find_vehicle, reset_caches

import app.models  # noqa: F401 — register models with Base


def run(
    eval_set_path: str = "evals/eval_set.json",
    output_path: str | None = None,
) -> str:
    """Run the full eval set against the current main DB. Returns the output path.

    Vehicles and their manuals must already be ingested (via `vehicle add` and
    `document add`); the runner does not auto-create or auto-ingest.
    """
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
            try:
                vehicle_id = find_vehicle(session, entry["vehicle_context"])
            except LookupError as exc:
                records.append(_lookup_error_record(entry, exc))
                continue

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


def _lookup_error_record(entry: dict, exc: LookupError) -> dict:
    return {
        "id": entry["id"],
        "failure_mode": entry["failure_mode"],
        "question": entry["question"],
        "passed": False,
        "rationale": f"vehicle not found: {exc}",
        "iterations": 0,
        "latency_s": 0.0,
        "answer": None,
        "sources": [],
        "expected_source_pdf": entry.get("expected_source_pdf"),
        "expected_source_pages": entry.get("expected_source_pages", []),
        "error": str(exc),
    }


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
        verbose=False,
    )


def _grade(entry: dict, result, substring, judge) -> GraderResult:
    if result is None:
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
