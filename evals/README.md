# RAG retrieval eval harness

A small, dependency-light harness that measures retrieval quality on a real service manual,
so every change to the retrieval pipeline is judged on a **measured delta**, not a claim.

## Why

The retrieval redesign's thesis is *precision on exact tokens* (DTC codes like `P0420`, part
numbers, torque specs) that dense embeddings structurally blur. This harness captures a
**dense-only baseline** and re-runs after each retrieval change (hybrid BM25+RRF, reranking,
query-adaptive routing, whole-table chunking) to prove — or disprove — each. (Table *extraction*
into separate chunks and LLM table summaries were both tried this way and **disproved**.)

## What it measures

Each golden question carries the manual page(s) that actually answer it (labels **verified by
searching the extracted manual text**, not guessed). Retrieval is run through the real
`RetrievalService.retrieve()` seam; chunks are mapped to their cited page, and we score:

- **Hit@k** — whether any relevant chunk is in the top-k (the metric the harness computes).
- **MRR** — mean reciprocal rank of the first relevant page.
- **Hit-rate** — share of questions with any relevant page in the top-k.

…reported overall and split by question type: **`exact_token`** (DTC codes / part numbers — where
BM25 should help most) vs **`conceptual`** (spec/procedure questions).

## Layout

- `metrics.py` — pure scoring functions (`hit_at_k`, `reciprocal_rank`). Unit-tested.
- `runner.py` — chunk→page-label adapter + aggregation + `run_eval()` over a retrieval service.
- `golden.py` — strict loader/validator for the golden set.
- `golden_questions.json` — 25 labeled F-150 questions; `golden_questions_tables.json` — 24
  table-lookup questions (capacities, torque, fluid types). Both verified against the manual.
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
| Dense-only (baseline) | 0.400 | 0.840 | 0.581 | 1.000 | 0.750 | 0.833 |
| + 1A reranker (cross-encoder, top-40→5) | 0.480 | **0.960** | 0.659 | 1.000 | 0.875 | 1.000 |
| + 1A BM25 hybrid (FTS5+RRF) | **0.560** | 0.880 | **0.691** | 0.800 | 0.875 | 0.917 |
| + 1A hybrid + reranker | 0.520 | 0.880 | 0.642 | 0.800 | 0.875 | 0.917 |

**Baseline finding (this reframed the redesign).** Dense retrieval is *not* broken on exact tokens
— it lands a relevant chunk in the top-5 for **every** literal-code query. The real headroom is
**hit@1 = 0.40** (the right chunk is rarely rank 1) and **paraphrase hit@5 = 0.75**.

**1A reranker.** Pool-expand to top-40 + local cross-encoder (FlashRank `ms-marco-MiniLM-L-12-v2`)
lifts **hit@5 0.84→0.96** and recovered 3 questions dense missed entirely. Best **hit@5**.

**1A BM25 hybrid (FTS5 + RRF).** Best **hit@1 (0.56)** and **MRR (0.69)**. *The eval caught a real bug
first:* OR-ing stopwords flooded BM25 with common-word matches and **regressed exact-token hit@5 to
0.60**; dropping function words restored it to 0.80. Even fixed, hybrid slightly regresses exact-token
recall (1.00→0.80) and **does not stack with the reranker** (combined is within noise of either alone).

## Table lookups + query-adaptive routing (the 1B outcome)

A second, **table-focused** golden set (`golden_questions_tables.json`, 24 verified questions: fluid
capacities, fluid types, torque specs) exposed the central tension — **the reranker that *makes*
procedures *craters* spec-table lookups:**

| Question type (atomic-table corpus, vehicle 4) | dense / `lookup` mode | reranker / `procedure` mode |
|---|---|---|
| **table lookups** (n=24) | **0.792** | 0.583 |
| **procedures + DTC** (n=25) | 0.840 | **0.960** |

No single config wins both. The fix is **query-adaptive routing**: the agent tags each `search_manuals`
call with `intent` (`lookup` \| `procedure`), and `RetrievalService.retrieve(mode=…)` skips the reranker
for lookups (dense already lands spec tables at 0.79) and applies it for procedures (0.96). Routed, the
system gets **0.792 on lookups *and* 0.960 on procedures** — beating all-reranker (0.58 lookups) and
all-dense (0.84 procedures). A one-off probe — the chat model labeling each golden question `lookup`
vs `procedure` — matched the expected route on **all 29 unambiguous questions** (24 table-lookups +
5 procedures); the remaining spec/DTC questions all routed (correctly) to `lookup`. This is a manual
spot-check, not a harness metric.

**What was tried and reverted.** Explicit table *extraction* (separate per-row chunks, then LLM table
summaries) was implemented and measured — both **regressed** retrieval (summaries drop the exact value;
per-row chunks doubled the corpus to ~19k and flooded the reranker). An exact-match BM25 "floor" was
also a no-op (RRF hybrid already subsumes it). All reverted. What shipped instead is much smaller:
**keep tables whole during normal chunking** (use `find_tables` bboxes only, so a window never cuts a
table and a table's bold cells aren't read as headings — corpus *shrinks* to 10.4k) **+ routing.**

**Honest read (n=49, deltas under ~0.08 are noisy).** Recommended config = **reranker on +
query-adaptive routing** (rerank procedures, plain dense for lookups). The reranker is opt-in (needs
`uv sync --group rerank`); routing is automatic once it is enabled. Grow the golden set before trusting
finer differences.
