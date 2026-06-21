# RAG retrieval eval harness

A small, dependency-light harness that measures retrieval quality on a real service manual,
so every change to the retrieval pipeline is judged on a **measured delta**, not a claim.

## Why

The retrieval redesign's thesis is *precision on exact tokens* (DTC codes like `P0420`, part
numbers, torque specs) that dense embeddings structurally blur. This harness captures a
**dense-only baseline** and re-runs after each retrieval phase (hybrid BM25+RRF, reranking,
table-aware ingestion, sectional context, parent-child) to prove — or disprove — each phase.

## What it measures

Each golden question carries the manual page(s) that actually answer it (labels **verified by
searching the extracted manual text**, not guessed). Retrieval is run through the real
`RetrievalService.retrieve()` seam; chunks are mapped to their cited page, and we score:

- **Recall@k** — fraction of a question's relevant pages found in the top-k.
- **MRR** — mean reciprocal rank of the first relevant page.
- **Hit-rate** — share of questions with any relevant page in the top-k.

…reported overall and split by question type: **`exact_token`** (DTC codes / part numbers — where
BM25 should help most) vs **`conceptual`** (spec/procedure questions).

## Layout

- `metrics.py` — pure scoring functions (`recall_at_k`, `reciprocal_rank`). Unit-tested.
- `runner.py` — chunk→page-label adapter + aggregation + `run_eval()` over a retrieval service.
- `golden.py` — strict loader/validator for the golden set.
- `golden_questions.json` — the 19 labeled F-150 questions (pages verified against the manual).
- `run_eval.py` — entrypoint that runs the set through the real `RetrievalService` and writes a report.

## Usage

```bash
# 1. Ingest the manual for a vehicle (one-time; the corpus under test).
# 2. Score retrieval and write evals/reports/<label>.json:
uv run python -m evals.run_eval --vehicle-id 1 --label baseline
# After Phase 1A lands, re-run to diff:
uv run python -m evals.run_eval --vehicle-id 1 --label 1A-hybrid
```

## Method notes

- **Relevance** = a retrieved chunk's content contains a distinguishing answer string
  (`answer_contains`, used for DTC codes / spec values) **or** its page is in a procedure's
  page cluster (`relevant_pages`). Content-match is stable across re-chunking; page numbers shift.
- **Caveat:** the exact-token questions are *easy* — the query contains the literal code, so they
  under-stress the BM25 thesis. Hardening with paraphrase queries (no literal token) is a TODO.

## Results

`k = 5`, F-150 corpus (11,193 chunks). 25 questions across 3 segments. hit@1 = top result relevant;
hit@5 = a relevant chunk in the top-5; MRR = rank of the first relevant chunk.

| Pipeline state | hit@1 | hit@5 | MRR | exact_token hit@5 | paraphrase hit@5 | conceptual hit@5 |
|---|---|---|---|---|---|---|
| **Dense-only (baseline)** | **0.400** | **0.840** | **0.581** | 1.000 | 0.750 | 0.833 |
| + 1A hybrid (BM25+RRF+rerank) | | | | | | |
| + 1B table-aware | | | | | | |
| + 1C sectional context | | | | | | |
| + 2D parent-child | | | | | | |

**Baseline finding (this reframed the redesign).** Dense retrieval is *not* broken on exact tokens
— it lands a relevant chunk in the top-5 for **every** literal-code query. The real headroom is:
(1) **hit@1 = 0.40** — the right chunk is rarely rank 1, the direct target of a cross-encoder
reranker; and (2) **paraphrase hit@5 = 0.75** — queries without the literal token are where dense
weakens and hybrid/BM25 can help. So 1A's expected win is in **ranking (hit@1 / MRR) and paraphrase
recall**, not the catastrophic exact-token failure the source research assumed. Lead with hit@1.
