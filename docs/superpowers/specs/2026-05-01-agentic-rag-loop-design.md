# Agentic RAG Loop — Design

**Status:** Draft for implementation
**Date:** 2026-05-01
**Scope:** Replace the single-pass retrieve-then-generate chat path with a hybrid-retrieval + reranker + bounded agentic loop. Re-chunk the corpus with table-aware ingest. Build an evaluation harness with 27 curated questions to measure each layer's contribution.

## Goals

1. Stop wrong-engine-variant chunks from reaching the LLM (e.g., a 4.2L spec answering a 6.0L question).
2. Surface table-row data (torque values, fuse ratings, DTC codes) reliably — currently lost when PyMuPDF flattens tables into linear text and chunking strips the column headers.
3. Recover from "top-5 missed the actual answer" via query rewriting + retry.
4. Measure that each architectural change actually moves pass@1 — no architectural decisions ungrounded by evidence.

## Non-goals

- Multi-vehicle queries. Each chat session is scoped to one vehicle.
- Web fallback (CRAG-style) — corpus is intentionally local.
- Tool-based agentic search (Anthropic's 2025 "list_sections / read_section" pattern) — deferred. The current design treats retrieval as a fixed pipeline; future work could expose document structure as tools the LLM calls.
- Fine-tuning. All graders use prompted instruction-tuned models.
- ColPali / multimodal page-image retrieval. Deferred until GPU is available.

## Design decisions (from brainstorm 2026-04-30)

| # | Question | Choice | Rationale |
|---|---|---|---|
| 1 | Which failure mode is hurting most? | Engine variant bleed + top-5 misses + tables | All three, with tables being a structural ingest issue not solvable by loop alone |
| 2 | Scope | Foundation (hybrid retrieval, table extraction, metadata, reranker) + Loop | Loop without foundation is fragile; foundation alone might suffice but loop addresses residual cases |
| 3 | Evaluation set | In scope, 27 curated entries (Appendix A) | Anthropic Jan 2026 guidance: build evaluation before optimizing |
| 4 | Reranker | In-process `sentence-transformers` + `bge-reranker-v2-m3` | CPU latency acceptable for CLI; no network dep; well-maintained dep |
| 5 | Loop UX | Verbose by default — show every step | User wants visibility into the loop's reasoning; helps catch bad rewrites |
| 6 | Engine variant filter | Hybrid: soft at retrieval, hard at grader | Strict guarantee + recoverable on classification errors |
| 7 | Grader model | `gemma4:e4b` (existing `context_model`) | Already pulled; ~1.5s grading overhead vs ~5s for chat model |

Approach selected: **Hard cutover.** `ChatService` and `RetrievalService` are deleted; replaced by `AgenticChatService` and `HybridRetrievalService`. Evaluation A/B happens across git commits, not via a feature flag.

## Section 1: Architecture overview

### Ingest pipeline (runs on `document add`)

```
PDF
 ├─→ PyMuPDF page text  ─→  StructuredChunker  ─→  prose chunks
 │
 └─→ PyMuPDF.find_tables ─→  TableChunker      ─→  table chunks (per-row + whole-table)
                                                          │
                                                          ▼
                                                  MetadataExtractor (LLM + regex)
                                                  → engine_variant, table_type
                                                          │
                                                          ▼
                                                  ContextualizationService (existing)
                                                  → context_summary
                                                          │
                                                          ▼
                                          embed via Ollama → write to:
                                                  • document_chunks (existing + new cols)
                                                  • document_chunks_fts (new FTS5)
                                                  • document_chunks_vec (new sqlite-vec)
```

### Query pipeline (runs on `chat ask` / `chat start`)

```
question + vehicle
       │
       ▼
  HybridRetrieval (top-30)        ← BM25 (FTS5) + cosine (sqlite-vec) fused via RRF
       │
       ▼
  CrossEncoderRerank (top-10)     ← bge-reranker-v2-m3 in-process
       │
       ▼
  RelevanceGrader (gemma4:e4b)    ← per-chunk yes/no, hard-rejects engine-variant mismatches
       │
       ├─ all rejected ──→ QueryRewriter ──→ retry (max 2 iterations)
       │
       ▼
  Generate answer (gemma4:26b)
       │
       ▼
  GroundednessGrader (gemma4:e4b) ← is the answer supported by the chunks?
       │
       ├─ fail ──→ QueryRewriter ──→ retry
       │
       ▼
  return answer + sources + loop trace
```

The loop is bounded at `max_iterations = 2` (so up to 3 retrieval passes total). State across iterations: original question (immutable), current rewritten query, accumulated rejected chunk IDs (excluded from next retrieval), iteration counter, prior failure reasons (passed to rewriter as context). On exhaustion: return a structured refusal explaining what was searched.

This shape matches the convergent 2024-2026 lab consensus: hybrid retrieval (Google, Microsoft, Anthropic), two-stage retrieval with cross-encoder reranker (Anthropic's published 35% to 67% failure-rate reduction with the full layered stack), bounded loop with sufficiency grader (Google SCA, ReAct, DSPy Refine).

## Section 2: Ingest pipeline changes

### New chunk kinds

Each PDF produces three kinds of chunks:
- `prose` — existing structure-aware chunks for narrative text
- `table_row` — one chunk per row with `[Section: X] [Table: Y] {column_headers}: {row_values}` prepended
- `table_whole` — entire table as markdown for queries needing cross-row context

Table detection happens *before* prose chunking via `Page.find_tables()`; table bounding boxes are excluded from the prose pass so a row's text doesn't appear twice.

### New columns on `document_chunks`

| Column | Type | Notes |
|---|---|---|
| `chunk_kind` | TEXT NOT NULL | `'prose' \| 'table_row' \| 'table_whole'` |
| `engine_variant` | TEXT NULL | `'4.2L' \| '6.0L' \| 'both' \| NULL` (NULL = applies to all) |
| `table_type` | TEXT NULL | `'torque' \| 'fluid' \| 'electrical' \| 'fitment' \| 'dtc' \| NULL` |
| `table_id` | TEXT NULL | groups `table_row` chunks back to their parent `table_whole` |

The existing `embedding_json` column is dropped; embeddings move to the `document_chunks_vec` virtual table.

### New `MetadataExtractor` service

Two-pass classifier:

1. **Filename regex** catches the easy cases — `\b(4\.2L|6\.0L|5\.2L|W12)\b` correctly tags ~90% of the Audi corpus from the filename alone (e.g., `15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf` → `4.2L`).
2. **LLM fallback** for ambiguous filenames (`01-MAINTENANCE.pdf`, `BASIC TROUBLE SHOOTING.pdf`) — `gemma4:e4b` reads a chunk sample and classifies. Output cached at the document level so we don't re-classify per chunk.

`table_type` is regex/keyword-based on the table's title and column headers (e.g., title contains "torque" or column headers include "Nm" → `torque`).

### Two new SQLite virtual tables

Following the Alex Garcia hybrid-search recipe (`sqlite-vec` + FTS5):

- `document_chunks_fts` — FTS5 virtual table over the **contextualized** text (the same enriched text that gets embedded). BM25 search.
- `document_chunks_vec` — `sqlite-vec` `vec0` virtual table for cosine similarity. Replaces `embedding_json`.

Both keyed by `chunk_id`. The text indexed in FTS5 matches the text fed to the embedder — this is Anthropic's "contextual BM25" recipe.

### Pipeline order at ingest

1. PyMuPDF: extract page text + detect tables
2. `TableChunker` emits `table_row` + `table_whole` chunks
3. `StructuredChunker` (existing) emits `prose` chunks for non-table regions
4. `MetadataExtractor` populates `engine_variant`, `table_type`, `table_id`
5. `ContextualizationService` (existing) produces `context_summary`
6. `EmbeddingService` (existing) embeds:
   `[Document: {file}] [Section: {section}] [Page: {page}] {context_summary}\n\n{content}`
7. Three rows written: `document_chunks` (metadata + content), `document_chunks_fts` (BM25 text), `document_chunks_vec` (embedding)

### Migration

Hard cutover. Drop existing `document_chunks` rows, ALTER TABLE for new columns, create the two virtual tables, re-run `document add` for each PDF. With no production data and 84 small-to-medium PDFs, full re-ingest is ~30-45 min on the user's machine, dominated by the contextualization step.

## Section 3: Retrieval pipeline

Two stages: hybrid candidate pull, then cross-encoder rerank. Both stages are scoped to the vehicle's chunks (via the existing document → vehicle relationship). Engine-variant filtering happens at the grader, not retrieval.

### Stage 1: HybridRetrieval (top-30)

```python
HybridRetrievalService.retrieve(
    query: str,
    vehicle_id: int,
    exclude_chunk_ids: frozenset[int] = frozenset(),
) -> list[tuple[Chunk, float]]  # ordered by RRF score, len <= 30
```

Single SQL CTE pulls top-30 from each retriever:

- **BM25**: `document_chunks_fts MATCH ? ORDER BY rank LIMIT 30` — query goes through FTS5's tokenizer; numeric/identifier terms (`P0301`, `M10`, `4.2L`) hit literal matches that vector search smears.
- **Vector**: `document_chunks_vec MATCH ? AND distance LIMIT 30` — cosine via `sqlite-vec`. Query embedded via existing `EmbeddingService.embed_query()`.

Both join `document_chunks` to filter by vehicle (`d.vehicle_id = ?`) and to exclude prior-iteration rejects (`c.id NOT IN exclude_chunk_ids`).

Fused via reciprocal rank fusion in the same CTE: `score = sum(1 / (60 + rank_i))` for `i` in `{bm25, vec}`. Take top-30 unique chunks ordered by fused score. RRF `k=60` is the cross-lab consensus default.

### Stage 2: CrossEncoderRerank (top-10)

```python
CrossEncoderReranker.rerank(
    query: str,
    candidates: list[Chunk],
) -> list[tuple[Chunk, float]]  # rescored, len <= 10
```

Uses `sentence-transformers` with `BAAI/bge-reranker-v2-m3` (278M params). Loaded lazily once per process. Scores `[query, contextualized_chunk_text]` pairs in a single batch. CPU latency: ~150ms for 30 candidates; faster on GPU automatically. Returns top-10 by rerank score.

### What this pipeline does NOT do

- **No engine-variant filter.** All variants pass through; the relevance grader rejects mismatches. A chunk tagged `engine_variant = NULL` (e.g., a maintenance schedule applying to both engines) reaches the grader and is judged on content.
- **No sufficiency check.** The retrieval pipeline's job is recall; precision is the loop's job.

### Performance targets

| Stage | Latency |
|---|---|
| Hybrid SQL CTE | <50ms for vehicle corpora ≤10k chunks |
| CPU rerank of 30 candidates | ~150ms |
| **Total per retrieval call** | **~200ms** |
| With 2 loop iterations | ~400-500ms of pure retrieval cost |

LLM call cost dominates; retrieval is not the bottleneck.

## Section 4: The agentic loop

The loop is a bounded state machine in a single Python module (`app/services/agentic_chat_service.py`). No framework — explicit `for iteration in range(MAX_ITERATIONS + 1)`. Per Anthropic's December 2024 "Building Effective Agents" guidance: many patterns can be implemented in a few lines of code.

### State machine

```
                                    ┌──────────────────┐
                                    │  start           │
                                    │  iter=0          │
                                    │  query=question  │
                                    └────────┬─────────┘
                                             ▼
                                    ┌──────────────────┐
                            ┌──────▶│  retrieve        │  HybridRetrieval(query, vehicle,
                            │       │                  │    exclude=rejected_chunk_ids)
                            │       └────────┬─────────┘  → top-10 chunks
                            │                ▼
                            │       ┌──────────────────┐
                            │       │ grade_relevance  │  per chunk: gemma4:e4b
                            │       │  (per chunk)     │  → {relevant: bool, reason}
                            │       └────────┬─────────┘  hard-reject engine_variant mismatch
                            │                ▼
                            │       ┌──────────────────┐
                            │       │ ≥1 relevant?     │
                            │       └────┬────────┬────┘
                            │       no   │        │   yes
                            │            ▼        ▼
                            │   ┌──────────────────┐ ┌──────────────────┐
                            │   │ iter < MAX?      │ │  generate        │
                            │   └────┬─────────┬───┘ │  gemma4:26b      │
                            │   yes  │         │  no └────────┬─────────┘
                            │        ▼         ▼              ▼
                            │   ┌──────────────────┐ ┌──────────────────┐
                            └───┤  query_rewrite   │ │ grade_groundedness│ gemma4:e4b
                                │  iter+=1         │ │                  │ → {grounded: bool,
                                │  add rejects to  │ └────────┬─────────┘   unsupported: [...]}
                                │   exclude set    │          ▼
                                └──────────────────┘ ┌──────────────────┐
                                         ▲           │   grounded?      │
                                         │           └────┬────────┬────┘
                                         │           no   │        │  yes
                                         │                ▼        ▼
                                         │      ┌──────────────────┐ ┌─────┐
                                         └──────┤  iter < MAX?     │ │  ✓  │
                                                └──────────────────┘ │ done│
                                                                     └─────┘
```

### Components

#### `RelevanceGrader.grade(chunk, question, vehicle)`

`gemma4:e4b` with structured JSON output. The prompt explicitly hands it `chunk.engine_variant` and `vehicle.engine` and instructs:

> "If the chunk is tagged for a specific engine variant and that variant differs from the vehicle's engine, return `{relevant: false, reason: 'engine variant mismatch'}` regardless of content."

This implements the hard side of the Q6 hybrid filter. Output: `{"relevant": bool, "reason": str}`.

#### `GroundednessGrader.grade(answer, chunks)`

`gemma4:e4b`. Returns `{"grounded": bool, "unsupported_claims": [str]}`. Fed to the loop trace so the user sees *why* a regeneration was triggered.

#### `QueryRewriter.rewrite(original_question, vehicle, prior_failure_reasons)`

`gemma4:e4b`. Crucial constraint: the rewriter conditions on the *original* question, not the previous rewrite, to prevent drift across iterations. Output: `{"rewritten_query": str, "rationale": str}`.

### Loop budget and state

- `MAX_ITERATIONS = 2` (so up to 3 retrieval passes: initial + 2 rewrites). Configurable but not exposed to users.
- State across iterations:
  - `original_question` — immutable
  - `current_query` — the rewritten query (or original on iter=0)
  - `rejected_chunk_ids` — accumulated, fed to retrieval as `exclude`
  - `iteration` — counter
  - `prior_failure_reasons` — list of strings, e.g. `"all chunks rejected as engine-variant mismatch"`, `"groundedness fail: claimed 50 Nm not in chunks"`. Fed to the rewriter as context.
- On exhaustion: structured refusal —
  > "I couldn't find that in the manuals for this vehicle. Searched 3 query variants. {N} chunks examined; {M} matched the wrong engine variant; {K} were off-topic."

This is honest about *what was searched* — useful for the user to know whether to ingest more docs.

### Verbose UX (Q5 = B)

Every state transition emits a Rich-formatted line via `app/utils/console.py`:

```
[1/3] Retrieving for "what is the head bolt torque?"
      Hybrid: 30 candidates → reranked: 10 → graded: 0 relevant
      (10 rejected: 7 engine variant mismatch, 3 off-topic)
↻ Query rewritten: "cylinder head bolt torque sequence 4.2L BFM V8"
[2/3] Retrieving with rewritten query
      Hybrid: 30 → reranked: 10 → graded: 4 relevant
✎ Generating answer with 4 chunks (gemma4:26b)
✓ Groundedness check: PASS
```

Loop trace also returned in the API as a structured object, so a future quiet-mode flag is trivial.

### Malformed grader output

If `gemma4:e4b` returns non-JSON, retry once with a stricter prompt reminder. On second failure:
- **Relevance grader fails open** (chunk passes — better to leak a candidate than lose it; the groundedness check is the safety net)
- **Groundedness grader fails closed** (treat as "not grounded" → trigger rewrite)

This asymmetry matches the research warning that small-model graders are noisy and one bad relevance rejection shouldn't derail the loop.

## Section 5: Evaluation harness

The evaluation harness lives at the repo root in `evals/` (separate from `tests/` — it produces metrics, not pass/fail). Purpose: measure whether each architectural change moves pass@1, per Anthropic's Jan 2026 guidance.

### Layout

```
evals/
├── eval_set.json           # the 27 curated entries (Appendix A)
├── run_evals.py            # CLI: `uv run python -m evals.run_evals [--out FILE]`
├── grader.py               # SubstringAnyGrader, LLMJudgeGrader
├── metrics.py              # pass@1, source-page precision, per-failure-mode breakdown
├── diff.py                 # compare two result files
└── results/                # gitignored; per-run JSON artifacts with timestamp + git SHA
```

### Entry schema (frozen)

```json
{
  "id": "evt_cyl_head_004",
  "question": "What is the maximum cylinder head warpage for a 2006 Audi A8 4.2L V8?",
  "vehicle_context": {"year": 2006, "make": "Audi", "model": "A8 Quattro", "engine": "4.2L V8 (BFM)"},
  "expected_answer_substrings": ["0.1 mm", "0.10 mm"],
  "expected_answer_summary": null,
  "expected_source_pdf": "15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf",
  "expected_source_pages": [4],
  "failure_mode": "engine_variant_trap",
  "grader_type": "substring_any",
  "trap_note": "If retrieved from 6.0L doc, would return 0.05 mm — half the actual tolerance"
}
```

`grader_type` is one of `substring_any` or `llm_judge`. For LLM-judge entries, `expected_answer_substrings` is `[]` and `expected_answer_summary` carries the rubric. The judge runs `gemma4:26b` (deliberately the same model used for generation, so the judge's rigor matches the generator's vocabulary).

### Runner mechanics

1. For each entry: ensure the vehicle exists in the test DB (auto-create from `vehicle_context`); ingest only the specific PDFs needed (subset of the 84 to keep runs fast); call `AgenticChatService.ask()` *as a library function*, not via the Typer CLI; collect answer, sources, full loop trace.
2. For each answer: run the configured grader → boolean pass.
3. **Source-page precision**: of the chunks the loop returned as sources, fraction whose `(pdf, page)` is in `expected_source_pages`.
4. **Source-page recall**: fraction of `expected_source_pages` covered.
5. Aggregate: pass@1 overall, pass@1 per `failure_mode`, source-page precision/recall, mean iterations used, mean wall-clock per query.

### A/B across commits

```bash
# baseline (current main, before this work)
git switch main && uv run python -m evals.run_evals --out evals/results/baseline.json

# feature
git switch feature/agentic-rag && uv run python -m evals.run_evals --out evals/results/feature.json

# diff
uv run python -m evals.diff evals/results/baseline.json evals/results/feature.json
```

The diff tool surfaces deltas in pass@1 by failure mode, list of regressed questions (passed before, failed now), list of newly-passing questions, latency cost. This is the gating signal for merge.

### Crucial constraint

The evaluation harness **must not be the only test signal**. Unit tests still cover the loop's state transitions, the graders' JSON parsing, the retrieval SQL, the rerank shapes. Evaluation tests *outcomes*; unit tests cover *correctness of components*. Both required.

### Distribution of the 27 entries

| Failure mode | Count |
|---|---|
| `engine_variant_trap` (4 paired) | 8 |
| `table_spec` | 6 |
| `general_procedure` | 3 |
| `negative` | 3 |
| `exact_identifier` (DTC, fuse) | 3 |
| `multi_hop` | 2 |
| `procedural_prose` | 2 |

See Appendix A for the full set.

## Section 6: Schema, configuration, testing, rollout

### Database migration (one-shot)

```sql
-- 1. Drop existing chunk rows (no production data)
DELETE FROM document_chunks;

-- 2. New columns on document_chunks
ALTER TABLE document_chunks ADD COLUMN chunk_kind TEXT NOT NULL DEFAULT 'prose';
ALTER TABLE document_chunks ADD COLUMN engine_variant TEXT NULL;
ALTER TABLE document_chunks ADD COLUMN table_type TEXT NULL;
ALTER TABLE document_chunks ADD COLUMN table_id TEXT NULL;
ALTER TABLE document_chunks DROP COLUMN embedding_json;  -- moved to vec0

CREATE INDEX idx_chunks_engine_variant ON document_chunks(engine_variant);
CREATE INDEX idx_chunks_table_id ON document_chunks(table_id);

-- 3. FTS5 virtual table for BM25
CREATE VIRTUAL TABLE document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    content=''
);

-- 4. sqlite-vec virtual table for cosine similarity
CREATE VIRTUAL TABLE document_chunks_vec USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[2560]   -- qwen3-embedding:4b dimension
);
```

A SQLAlchemy migration script in `app/db/migrations/001_hybrid_retrieval.py` runs once at first invocation after upgrade. Existing schema setup in `app/db/session.py:get_session()` invokes it idempotently.

Reset path for development: `uv run mechanic-sidekick db reset` (new command) drops `data/app.db` and `data/documents/*` cleanly.

### New configuration (added to `app/config.py`)

| Key | Default | Purpose |
|---|---|---|
| `bm25_top_k` | 30 | Per-retriever pull before RRF |
| `vector_top_k` | 30 | Per-retriever pull before RRF |
| `rrf_k` | 60 | RRF constant (cross-lab consensus) |
| `rerank_top_k` | 10 | Reranker output count |
| `reranker_model` | `BAAI/bge-reranker-v2-m3` | sentence-transformers model id |
| `grader_model` | `gemma4:e4b` | reuses existing `context_model` |
| `max_loop_iterations` | 2 | bounded retry budget |
| `loop_verbose` | true | Q5 = B (verbose default) |

The existing `top_k_chunks` is removed (subsumed by `rerank_top_k`).

### New Python dependencies

```toml
sqlite-vec = "^0.1"
sentence-transformers = "^3"
```

Plus a one-time download of `BAAI/bge-reranker-v2-m3` (~500MB) cached under `~/.cache/huggingface`. First invocation after install fetches it; subsequent runs are offline.

### Testing strategy

**Unit tests** (`tests/`, mocked Ollama, in-memory SQLite):
- `test_table_chunker.py` — table extraction → row + whole chunks, header preservation
- `test_metadata_extractor.py` — filename regex tags 4.2L/6.0L correctly; ambiguous filenames trigger LLM fallback
- `test_hybrid_retrieval.py` — RRF math, BM25 + vector fusion, exclude_chunk_ids respected, vehicle scoping
- `test_relevance_grader.py` — JSON parsing, malformed-output retry, engine-variant hard reject
- `test_groundedness_grader.py` — JSON parsing, fail-closed semantics
- `test_query_rewriter.py` — conditioning on original question (not previous rewrite)
- `test_agentic_chat_service.py` — state machine transitions, max-iteration enforcement, refusal path, exclude-set accumulation

**Evaluation tests** (`evals/`, real Ollama, real reranker, real DB with subset of PDFs ingested): the 27 entries. Run before merge; pass@1 must not regress vs main on any failure_mode.

The reranker download is mocked in unit tests via dependency injection of a `Reranker` protocol — production uses `BgeReranker`, tests use `IdentityReranker` (returns input order). Keeps unit-test execution offline and fast.

### Rollout

Single-user CLI, no production. Rollout = merge to main, run `uv sync`, run `mechanic-sidekick db reset`, run `mechanic-sidekick document add` for each PDF (or batch script for the 84 Audi files). Total elapsed: ~30-45 minutes on the user's machine, dominated by contextualization.

No backwards-compat shims, no feature flag wrapping the loop, no parallel old/new path.

### Files created / modified

**Created:**
- `app/services/agentic_chat_service.py` (loop)
- `app/services/hybrid_retrieval_service.py`
- `app/services/cross_encoder_reranker.py`
- `app/services/metadata_extractor.py`
- `app/services/table_chunker.py`
- `app/rag/grader.py` (RelevanceGrader, GroundednessGrader)
- `app/rag/query_rewriter.py`
- `app/db/migrations/001_hybrid_retrieval.py`
- `evals/eval_set.json`, `evals/run_evals.py`, `evals/grader.py`, `evals/metrics.py`, `evals/diff.py`
- New unit tests for each of the above

**Modified:**
- `app/cli.py` — `_make_chat_service()` returns `AgenticChatService`; add `db reset` command
- `app/services/document_service.py` — invoke `TableChunker` before `StructuredChunkingService`; populate new metadata
- `app/repositories/chunk_repository.py` — write to `document_chunks_fts` and `document_chunks_vec` on insert
- `app/config.py` — new keys above
- `pyproject.toml` — add `sqlite-vec`, `sentence-transformers`

**Deleted:**
- `app/services/retrieval_service.py` (replaced by `HybridRetrievalService`)
- `app/services/chat_service.py` (replaced by `AgenticChatService`)

## Open issues / known asymmetries

1. **6.0L W12 crankshaft internals not in corpus.** The 6.0L block-internals doc is not in `data/documents/`. Several evaluation entries are 4.2L-only because of this; for the equivalent 6.0L questions the system will correctly refuse — the `negative` entries cover this behavior.
2. **PDFs are in a subdirectory** (`data/documents/Audi_A8_2004-2009 Manuals/`). The current `document_service` may not recurse; verify before the first `document add` batch and either fix the service or flatten the directory.
3. **Some specs aren't in any of these PDFs.** Oil/coolant capacity defers to ServiceNet; CCA/battery Ah aren't in the corpus. The evaluation set respects this — no questions ask for content the corpus doesn't have (except the deliberate `negative` entries).
4. **Two false-pair traps to avoid in future evaluation expansion:** spark plug torque (30 Nm on both engines), valve seat angle (45° on both). Excluded from current evaluation set.

## Appendix A: Curated 27 evaluation entries

The full list, distributed across failure modes. Sourced from agent mining 2026-04-30, all specs verified against real PDF page content.

### Engine variant trap (paired) — 8 entries

1. `evt_cyl_head_002` — 4.2L valve cover bolt torque (10 Nm) | pair with `evt_cyl_head_003` (6.0L = 8 Nm)
2. `evt_cyl_head_003` — 6.0L valve cover bolt torque (8 Nm)
3. `evt_cyl_head_004` — 4.2L cylinder head warpage limit (0.1 mm) | pair with `evt_cyl_head_005` (6.0L = 0.05 mm)
4. `evt_cyl_head_005` — 6.0L cylinder head warpage limit (0.05 mm)
5. `evt_assembly_002` — 4.2L vibration damper (22 Nm, 8 bolts) | pair with `evt_assembly_003` (6.0L = 100 Nm + 90°, single bolt)
6. `evt_assembly_003` — 6.0L vibration damper (100 Nm + 90°)
7. `evt_assembly_004` — 4.2L drive plate (30 Nm + 90°) | pair with `evt_assembly_005` (6.0L = 60 Nm + 90°)
8. `evt_assembly_005` — 6.0L drive plate (60 Nm + 90°)

### Table spec — 6 entries

9. `evt_table_001` — Front brake disc wear limit, FNR 42 AL 1LJ caliper (33 mm) — column-binding test
10. `evt_table_002` — Rear brake pad wear limit, PR 1KW (3 mm)
11. `evt_table_004` — Front track width, sport suspension PR 2MA (1630 mm)
12. `evt_table_008` — 09E transmission code GUN, complete front axle ratio (4.055) — discriminates W12 from V8 codes
13. `evt_table_009` — 6.0L W12 firing order (1-12-5-8-3-10-6-7-2-11-4-9)
14. `evt_table_010` — 6.0L BSB oil pressure at idle (0.8 bar) — tests nested header structure

### Exact identifier — 3 entries

15. `evt_dtc_001` — DTC P0301 description ("Cylinder 1 Misfire Detected")
16. `evt_dtc_003` — DTC P0420 description + corrective action (oxygen sensor)
17. `evt_fuse_001` — Fuse 25 in IP left-side panel (40A, J400 wiper module) — tests panel-side disambiguation

### Multi-hop — 2 entries

18. `evt_multihop_001` — Brake bleed: DOT 4 fluid spec (49-BRAKES TECH DATA) + bleeder torque (47-HYDRAULIC) — two PDFs
19. `evt_assembly_006` — Main bearing tightening sequence (parts list page 62 + procedure page 68) — same PDF, two pages

### General procedure — 3 entries

20. `evt_proc_002` — Wheel bolt torque (120 Nm) + pattern (diagonal) — two facts in one section
21. `evt_proc_003` — Front brake pad replacement procedure — LLM-judge grader on multi-step procedure
22. `evt_proc_004` — Front FNR G60 bleeder screw torque (15 Nm) + Lithium Grease on threads

### Negative — 3 entries

23. `evt_dtc_005_negative` — DTC P0500 (verified absent from BFM index) — system must refuse to invent
24. `evt_negative_001` — CCM-R brake option (fictional trim) — system must not confuse with real CISC ceramic
25. `evt_negative_002` — Oil change interval in miles (manual defers to ServiceNet, no number) — must not fabricate

### Procedural prose — 2 entries

26. `evt_assembly_001` — 4.2L conrod bolt torque (30 Nm + 90°) + always-replace note
27. `evt_assembly_007` — 4.2L TDC cyl-5 setting procedure (multi-figure procedural prose, special tool 3242)

Each entry includes `expected_source_pdf`, `expected_source_pages`, `expected_answer_substrings` (or `expected_answer_summary` for LLM-judge), `failure_mode`, `grader_type`, and `trap_note`/`notes` per the schema in Section 5. Full JSON to be authored into `evals/eval_set.json` during implementation.

## Appendix B: Research references

Primary sources consulted during the brainstorm.

### Anthropic
- [Introducing Contextual Retrieval (Sept 2024)](https://www.anthropic.com/news/contextual-retrieval) — full layered stack, 67% failure-rate reduction
- [Building Effective Agents (Dec 2024)](https://www.anthropic.com/research/building-effective-agents) — workflow-vs-agent, evaluator-optimizer pattern
- [Building agents with the Claude Agent SDK (Sept 2025)](https://claude.com/blog/building-agents-with-the-claude-agent-sdk) — agentic search via structured tools
- [Effective context engineering for AI agents (Sept 2025)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — just-in-time retrieval
- [Demystifying evaluations for AI agents (Jan 2026)](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — code-graders first

### Google / DeepMind
- [Vertex AI RAG Engine overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-overview)
- [Vertex AI hybrid search](https://docs.cloud.google.com/vertex-ai/docs/vector-search/about-hybrid-search)
- [Vertex AI Cross Corpus Retrieval (agentic)](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/cross-corpus-retrieval)
- [ReAct (arXiv 2210.03629)](https://arxiv.org/abs/2210.03629)

### Microsoft
- [Azure AI Search Hybrid Overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
- [Outperforming vector with hybrid + reranking](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/azure-ai-search-outperforming-vector-search-with-hybrid-retrieval-and-reranking/3929167)
- [GraphRAG (arXiv 2404.16130)](https://arxiv.org/abs/2404.16130) — surveyed but not adopted

### Self-correcting RAG
- [CRAG (arXiv 2401.15884)](https://arxiv.org/abs/2401.15884) — corrective retrieval, decompose-recompose
- [Self-RAG (arXiv 2310.11511)](https://arxiv.org/abs/2310.11511) — surveyed but rejected (requires fine-tuning)
- [HyDE (arXiv 2212.10496)](https://arxiv.org/abs/2212.10496)

### Tables and PDF extraction
- [PyMuPDF Page.find_tables](https://artifex.com/blog/table-recognition-extraction-from-pdfs-pymupdf-python)
- [Docling (arXiv 2501.17887)](https://arxiv.org/html/2501.17887v1) — surveyed; deferred to future work
- [Alex Garcia: hybrid FTS5 + sqlite-vec](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html) — adopted recipe
- [LlamaIndex: Mastering PDFs — sections, headings, tables](https://www.llamaindex.ai/blog/mastering-pdfs-extracting-sections-headings-paragraphs-and-tables-with-cutting-edge-parser-faea18870125)

### Other
- [DSPy docs](https://dspy.ai/) — surveyed; module pattern adopted conceptually, optimizer not used
- [glaforge: Advanced RAG / RRF (2026)](https://glaforge.dev/posts/2026/02/10/advanced-rag-understanding-reciprocal-rank-fusion-in-hybrid-search/) — RRF k=60 default
