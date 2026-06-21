"""Run the golden-question set through the real RetrievalService and write a metrics report.

This is the harness entrypoint that captures the dense-only baseline (and, after each
retrieval phase, the new numbers to diff against it). Thin wiring only — the scored logic
lives in evals.runner / evals.metrics, which are unit-tested.

Usage:
    uv run python -m evals.run_eval --vehicle-id 1 --label baseline
"""
import argparse
import json
from pathlib import Path

from app.cli import get_session  # reuse the same DB session seam the CLI/app use
from app.config import settings
from app.repositories.chunk_repository import ChunkRepository
from app.services.llm_factory import make_embedding_service, make_reranker
from app.services.retrieval_service import RetrievalService
from evals.golden import load_golden
from evals.runner import run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RAG eval harness against an ingested vehicle.")
    parser.add_argument("--vehicle-id", type=int, required=True)
    parser.add_argument("--golden", default="evals/golden_questions.json")
    parser.add_argument("--k", type=int, default=settings.top_k_chunks)
    parser.add_argument("--label", default="baseline", help="report label (e.g. baseline, 1A-rerank)")
    parser.add_argument("--rerank-provider", default=settings.rerank_provider, help="none | local")
    parser.add_argument("--rerank-candidates", type=int, default=settings.rerank_candidates)
    parser.add_argument("--hybrid", action="store_true", help="fuse BM25 (FTS5) with cosine via RRF")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    settings.rerank_provider = args.rerank_provider  # let the CLI flags drive the seams for an A/B run
    questions = load_golden(args.golden)
    embedding = make_embedding_service(settings)
    reranker = make_reranker(settings)
    with get_session() as session:
        retrieval = RetrievalService(ChunkRepository(session), embedding, args.k, reranker,
                                     args.rerank_candidates, args.hybrid, settings.rrf_k)
        report = run_eval(retrieval, args.vehicle_id, questions, args.k)

    report.update({"label": args.label, "k": args.k, "vehicle_id": args.vehicle_id,
                   "rerank_provider": args.rerank_provider, "hybrid": args.hybrid})
    s = report["summary"]
    print(f"[{args.label}] n={s['n']}  hit@1={s['hit_rate_at_1']:.3f}  "
          f"hit@{args.k}={s['hit_rate']:.3f}  MRR={s['mrr']:.3f}")
    for qtype, r in sorted(s["by_type"].items()):
        print(f"  {qtype:12s} n={r['n']:3d}  hit@1={r['hit_rate_at_1']:.3f}  "
              f"hit@{args.k}={r['hit_rate']:.3f}  MRR={r['mrr']:.3f}")

    out = Path(args.out or f"evals/reports/{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
