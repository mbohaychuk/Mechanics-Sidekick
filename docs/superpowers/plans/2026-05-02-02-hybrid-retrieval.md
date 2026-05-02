# Hybrid Retrieval + Reranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `RetrievalService` (single-pass cosine over JSON-stored embeddings) with a two-stage hybrid retrieval pipeline: BM25 (FTS5) + cosine (sqlite-vec) fused via Reciprocal Rank Fusion to top-30, then reranked to top-10 via `BAAI/bge-reranker-v2-m3` cross-encoder. After this plan ships, retrieval is precise enough for Plan 3's grader to make meaningful keep/reject decisions.

**Architecture:** Two new services. `HybridRetrievalService` runs a single SQL CTE that pulls top-30 from each retriever and fuses via RRF (`score = sum(1 / (60 + rank_i))`), scoped by `vehicle_id` and excluding rejected chunk ids from the loop. `CrossEncoderReranker` is a thin wrapper around `sentence-transformers` with a `Reranker` Protocol so unit tests can inject an `IdentityReranker`. The reranker model is downloaded lazily on first use (cached in `~/.cache/huggingface`).

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, sqlite-vec (already loaded by Plan 1), SQLite FTS5, `sentence-transformers>=3` (loads `transformers`, `torch`, `huggingface_hub`), Ollama (for query embedding), pytest.

---

## Source Spec

`docs/superpowers/specs/2026-05-01-agentic-rag-loop-design.md` — Section 3 (retrieval pipeline). Open issue: dependency on Plan 1's FTS5 + vec0 tables existing.

## File Structure

**Created:**
- `app/services/hybrid_retrieval_service.py` — RRF over BM25 + sqlite-vec
- `app/services/reranker.py` — `Reranker` Protocol, `IdentityReranker` (test), `BgeReranker` (production)
- `tests/test_services/test_hybrid_retrieval_service.py`
- `tests/test_services/test_reranker.py`

**Modified:**
- `app/config.py` — add `bm25_top_k`, `vector_top_k`, `rrf_k`, `rerank_top_k`, `reranker_model`
- `pyproject.toml` — add `sentence-transformers>=3`
- `app/cli.py` — `_make_chat_service` will be rewritten in Plan 3, but we update its retrieval wiring path now in preparation

**Deleted:**
- `app/services/retrieval_service.py` (replaced by `HybridRetrievalService`)
- `app/rag/similarity.py` (no longer used — sqlite-vec computes distances)
- `tests/test_services/test_retrieval_service.py` (already skipped by Plan 1; remove the file)
- `tests/test_rag/test_similarity.py` (similarity module is gone)

**Untouched:** `chat_service.py` and its test stay skipped — Plan 3 deletes them.

---

## Task 1: Add sentence-transformers and configuration keys

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml` — append `"sentence-transformers>=3"` to `dependencies`:

```toml
dependencies = [
    "ollama>=0.4",
    "sqlalchemy>=2.0",
    "pydantic-settings>=2.0",
    "pymupdf>=1.24",
    "typer>=0.12",
    "rich>=13.0",
    "numpy>=1.26",
    "python-dotenv>=1.0",
    "sqlite-vec>=0.1",
    "sentence-transformers>=3",
]
```

- [ ] **Step 2: Sync**

Run: `uv sync --group dev`
Expected: pulls `sentence-transformers`, `transformers`, `torch`, `huggingface_hub`. ~500MB-1.5GB depending on torch flavour. May take a minute.

- [ ] **Step 3: Verify torch is importable**

Run: `uv run python -c "import sentence_transformers; print(sentence_transformers.__version__)"`
Expected: a version string (3.x.y). No tracebacks.

- [ ] **Step 4: Update Settings**

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

    # Hybrid retrieval (Plan 2)
    bm25_top_k: int = 30
    vector_top_k: int = 30
    rrf_k: int = 60
    rerank_top_k: int = 10
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

`top_k_chunks` is *removed* — `rerank_top_k` subsumes it. Plan 1 left it in place; we drop it now.

- [ ] **Step 5: Verify settings parse**

Run: `uv run python -c "from app.config import settings; print(settings.bm25_top_k, settings.reranker_model)"`
Expected: `30 BAAI/bge-reranker-v2-m3`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/ -v`
Expected: green except the two skipped retrieval/chat files. (`test_config.py` may need updating if it asserts `top_k_chunks`. If so, replace the assertion with `bm25_top_k` and `rerank_top_k`.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/config.py
# also stage tests/test_config.py if you edited it
git commit -m "feat: add sentence-transformers + hybrid retrieval config keys"
```

---

## Task 2: Reranker Protocol + IdentityReranker

**Files:**
- Create: `app/services/reranker.py`
- Create: `tests/test_services/test_reranker.py`

The `Reranker` Protocol describes the rerank interface; `IdentityReranker` returns chunks in the input order with a placeholder score (used by unit tests to keep them offline). `BgeReranker` (Task 3) does the real work.

- [ ] **Step 1: Write failing tests for IdentityReranker**

Create `tests/test_services/test_reranker.py`:

```python
# tests/test_services/test_reranker.py
from unittest.mock import MagicMock
from app.models.document_chunk import DocumentChunk
from app.services.reranker import IdentityReranker, Reranker


def _chunk(content: str) -> DocumentChunk:
    return DocumentChunk(document_id=1, chunk_index=0, content=content)


def test_identity_reranker_preserves_order_and_truncates_to_top_k():
    chunks = [_chunk("a"), _chunk("b"), _chunk("c"), _chunk("d")]
    reranker: Reranker = IdentityReranker()
    out = reranker.rerank(query="anything", candidates=chunks, top_k=2)

    assert [c.content for c, _ in out] == ["a", "b"]
    assert all(score == 1.0 for _, score in out)


def test_identity_reranker_handles_empty_input():
    reranker = IdentityReranker()
    assert reranker.rerank(query="x", candidates=[], top_k=5) == []
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_services/test_reranker.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement Protocol + Identity**

Create `app/services/reranker.py`:

```python
# app/services/reranker.py
"""Reranker abstraction.

The hybrid retrieval pipeline pulls top-30 candidates fast (FTS5 + vec0).
A reranker rescores those 30 with a cross-encoder for higher precision and
returns the top-10. Production uses BgeReranker (BAAI/bge-reranker-v2-m3);
unit tests use IdentityReranker to stay offline.
"""
from typing import Protocol

from app.models.document_chunk import DocumentChunk


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        """Return chunks rescored against the query, sorted descending, len <= top_k."""
        ...


class IdentityReranker:
    """No-op reranker: preserves input order, scores all 1.0. For tests."""

    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        return [(c, 1.0) for c in candidates[:top_k]]
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_services/test_reranker.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/reranker.py tests/test_services/test_reranker.py
git commit -m "feat: add Reranker protocol + IdentityReranker"
```

---

## Task 3: BgeReranker — sentence-transformers cross-encoder

**Files:**
- Modify: `app/services/reranker.py`
- Modify: `tests/test_services/test_reranker.py`

`BgeReranker` lazily loads `BAAI/bge-reranker-v2-m3` via `sentence-transformers`'s `CrossEncoder` wrapper. We can't realistically test the real model in unit tests (it's 500MB to download); instead we test the behaviour of the wrapper itself by injecting a fake `CrossEncoder`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_reranker.py`:

```python
def test_bge_reranker_calls_cross_encoder_with_pairs_and_returns_top_k():
    from app.services.reranker import BgeReranker

    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    class FakeCE:
        def __init__(self):
            self.calls = []

        def predict(self, pairs):
            self.calls.append(pairs)
            # Simulate scores: c > a > b
            scoremap = {"a": 0.5, "b": 0.1, "c": 0.9}
            return [scoremap[p[1]] for p in pairs]

    fake = FakeCE()
    reranker = BgeReranker(model_name="fake/model", cross_encoder=fake)
    out = reranker.rerank(query="q", candidates=chunks, top_k=2)

    # Pairs were (query, content) for each candidate.
    assert fake.calls == [[("q", "a"), ("q", "b"), ("q", "c")]]
    # Top-2 by score: c then a.
    assert [c.content for c, _ in out] == ["c", "a"]
    assert out[0][1] == 0.9
    assert out[1][1] == 0.5


def test_bge_reranker_returns_empty_when_no_candidates():
    from app.services.reranker import BgeReranker

    class FakeCE:
        def predict(self, pairs):
            raise AssertionError("should not call predict on empty")

    reranker = BgeReranker(model_name="fake", cross_encoder=FakeCE())
    assert reranker.rerank(query="q", candidates=[], top_k=10) == []
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_services/test_reranker.py::test_bge_reranker_calls_cross_encoder_with_pairs_and_returns_top_k -v`
Expected: FAIL — `BgeReranker` does not exist.

- [ ] **Step 3: Implement BgeReranker**

Append to `app/services/reranker.py`:

```python
class BgeReranker:
    """Cross-encoder reranker backed by sentence-transformers.

    The model is loaded lazily on first rerank() call (or at construction if
    a cross_encoder is injected). Scores `[query, chunk.content]` pairs in a
    single batch.
    """

    def __init__(
        self,
        model_name: str,
        cross_encoder=None,
    ) -> None:
        self._model_name = model_name
        self._ce = cross_encoder

    def _load(self):
        if self._ce is None:
            from sentence_transformers import CrossEncoder
            self._ce = CrossEncoder(self._model_name)
        return self._ce

    def rerank(
        self,
        query: str,
        candidates: list[DocumentChunk],
        top_k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        if not candidates:
            return []
        ce = self._load()
        pairs = [(query, c.content) for c in candidates]
        scores = ce.predict(pairs)
        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(c, float(s)) for c, s in scored[:top_k]]
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_services/test_reranker.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/reranker.py tests/test_services/test_reranker.py
git commit -m "feat: add BgeReranker using sentence-transformers CrossEncoder"
```

---

## Task 4: HybridRetrievalService — RRF over FTS5 + vec0

**Files:**
- Create: `app/services/hybrid_retrieval_service.py`
- Create: `tests/test_services/test_hybrid_retrieval_service.py`

The retrieval service runs a single SQL CTE that:
1. Pulls top-`bm25_top_k` chunk_ids by FTS5 BM25 rank for the query.
2. Pulls top-`vector_top_k` chunk_ids by sqlite-vec cosine distance for the query embedding.
3. Computes RRF: `score = sum(1.0 / (rrf_k + rank_i))` per chunk_id across both lists.
4. Joins `document_chunks` to apply `vehicle_id` filter and exclude rejected chunk ids.
5. Returns top-30 unique chunks, ordered by fused score.

The CTE is the right shape because RRF needs ranks computed over the *unfiltered* candidate set per retriever (the spec says to filter at the join, after the per-retriever top-30 is settled).

- [ ] **Step 1: Write the test fixture and the first failing test**

Create `tests/test_services/test_hybrid_retrieval_service.py`:

```python
# tests/test_services/test_hybrid_retrieval_service.py
import pytest
from unittest.mock import MagicMock

from app.models.document_chunk import DocumentChunk
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_retrieval_service import HybridRetrievalService


@pytest.fixture
def vehicle_with_corpus(db_session):
    """Insert two vehicles (to test scoping) and a tiny chunk corpus."""
    v1 = VehicleRepository(db_session).create(year=2006, make="Audi", model="A8", engine="4.2L V8")
    v2 = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L V8")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    doc1 = doc_repo.create(v1.id, "audi.pdf", "/tmp/a.pdf")
    doc1.processing_status = "ready"
    doc2 = doc_repo.create(v2.id, "ford.pdf", "/tmp/f.pdf")
    doc2.processing_status = "ready"
    db_session.flush()

    repo = ChunkRepository(db_session)
    repo.bulk_create([
        # Audi chunks — chunk_id 1..3
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=0, page_number=1,
                                content="Cylinder head bolt torque is 129 Nm"),
            indexable_text="Cylinder head bolt torque 129 Nm 4.2L V8 Audi",
            embedding=[1.0, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=1, page_number=2,
                                content="Wheel bolt torque 120 Nm diagonal pattern"),
            indexable_text="Wheel bolt torque 120 Nm diagonal pattern Audi",
            embedding=[0.0, 1.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc1.id, chunk_index=2, page_number=3,
                                content="Brake fluid DOT 4 specification"),
            indexable_text="Brake fluid DOT 4 specification Audi",
            embedding=[0.0, 0.0, 1.0, 0.0],
        ),
        # Ford chunk — chunk_id 4 — must NOT be returned for vehicle=v1.
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc2.id, chunk_index=0, page_number=1,
                                content="Cylinder head bolt torque is 95 Nm"),
            indexable_text="Cylinder head bolt torque 95 Nm 5.0L V8 Ford F-150",
            embedding=[0.9, 0.1, 0.0, 0.0],  # very close to query — vector match
        ),
    ])
    db_session.flush()
    return v1, v2


def _make_service(db_session, query_embedding=None) -> HybridRetrievalService:
    embedding = MagicMock(spec=EmbeddingService)
    embedding.embed_query.return_value = query_embedding or [1.0, 0.0, 0.0, 0.0]
    return HybridRetrievalService(
        session=db_session,
        embedding_service=embedding,
        bm25_top_k=10,
        vector_top_k=10,
        rrf_k=60,
        result_top_k=30,
    )


def test_retrieve_returns_chunks_scoped_to_vehicle(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    results = svc.retrieve(query="head bolt torque", vehicle_id=v1.id)

    contents = [c.content for c, _ in results]
    # Audi chunks may appear; Ford's "95 Nm" chunk must NOT.
    assert "Cylinder head bolt torque is 95 Nm" not in contents
    assert "Cylinder head bolt torque is 129 Nm" in contents


def test_retrieve_excludes_chunk_ids(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)

    # First call: collect the top result.
    initial = svc.retrieve(query="cylinder head torque", vehicle_id=v1.id)
    excluded_id = initial[0][0].id

    # Second call with that chunk excluded.
    refined = svc.retrieve(
        query="cylinder head torque",
        vehicle_id=v1.id,
        exclude_chunk_ids=frozenset({excluded_id}),
    )
    assert all(c.id != excluded_id for c, _ in refined)


def test_retrieve_returns_empty_when_no_match(db_session):
    """Vehicle with no documents → empty list, no embedding call wasted."""
    v = VehicleRepository(db_session).create(year=2024, make="Tesla", model="Y", engine="electric")
    db_session.flush()
    svc = _make_service(db_session)
    assert svc.retrieve(query="anything", vehicle_id=v.id) == []


def test_retrieve_deduplicates_when_chunk_appears_in_both_retrievers(db_session, vehicle_with_corpus):
    """A chunk that ranks #1 by BM25 *and* #1 by vector must appear once with summed RRF score."""
    v1, _ = vehicle_with_corpus
    # Use an embedding aligned with chunk-1 (which also has 'cylinder head' text).
    svc = _make_service(db_session, query_embedding=[1.0, 0.0, 0.0, 0.0])
    results = svc.retrieve(query="cylinder head", vehicle_id=v1.id)

    ids = [c.id for c, _ in results]
    assert len(ids) == len(set(ids))  # no duplicates

    # The top result should be the chunk that ranks well in both.
    assert "129 Nm" in results[0][0].content


def test_retrieve_orders_by_fused_rrf_score_descending(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    results = svc.retrieve(query="bolt torque", vehicle_id=v1.id)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_services/test_hybrid_retrieval_service.py -v`
Expected: FAIL — `HybridRetrievalService` does not exist.

- [ ] **Step 3: Implement HybridRetrievalService**

Create `app/services/hybrid_retrieval_service.py`:

```python
# app/services/hybrid_retrieval_service.py
"""Two-retriever fusion: BM25 (FTS5) + cosine (sqlite-vec) → RRF → top-K.

A single SQL CTE pulls per-retriever top-K candidates, fuses them via
Reciprocal Rank Fusion (score = sum(1.0 / (rrf_k + rank_i))), and joins
document_chunks to scope by vehicle and exclude rejected chunk ids.

This is the spec's stage-1 retriever; downstream callers reranks the result
to top-10 with a cross-encoder.
"""
import struct
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import EmbeddingService


class HybridRetrievalService:
    def __init__(
        self,
        session: Session,
        embedding_service: EmbeddingService,
        bm25_top_k: int = 30,
        vector_top_k: int = 30,
        rrf_k: int = 60,
        result_top_k: int = 30,
    ) -> None:
        self._session = session
        self._embedding = embedding_service
        self._bm25_top_k = bm25_top_k
        self._vector_top_k = vector_top_k
        self._rrf_k = rrf_k
        self._result_top_k = result_top_k

    def retrieve(
        self,
        query: str,
        vehicle_id: int,
        exclude_chunk_ids: frozenset[int] = frozenset(),
    ) -> list[tuple[DocumentChunk, float]]:
        """Return top-K chunks for the vehicle, fused over BM25 + vector retrievers.

        Args:
            query: User question (may be a rewrite from the agentic loop).
            vehicle_id: Restrict to chunks from documents owned by this vehicle.
            exclude_chunk_ids: Chunk ids the loop has already rejected.

        Returns:
            list of (chunk, fused_score) — empty if no chunks match.
        """
        query_emb = self._embedding.embed_query(query)
        emb_blob = struct.pack(f"{len(query_emb)}f", *query_emb)

        sql = text(_HYBRID_SQL)
        sql = sql.bindparams(
            bindparam("exclude_ids", expanding=True),
        )
        rows = self._session.execute(
            sql,
            {
                "query": query,
                "embedding": emb_blob,
                "vehicle_id": vehicle_id,
                "bm25_k": self._bm25_top_k,
                "vec_k": self._vector_top_k,
                "rrf_k": self._rrf_k,
                "result_k": self._result_top_k,
                # SQLite IN-clause needs at least one element; sentinel -1 never matches a real id.
                "exclude_ids": list(exclude_chunk_ids) or [-1],
            },
        ).fetchall()

        if not rows:
            return []

        chunk_ids_in_order = [row[0] for row in rows]
        score_by_id = {row[0]: float(row[1]) for row in rows}

        chunks = (
            self._session.query(DocumentChunk)
            .filter(DocumentChunk.id.in_(chunk_ids_in_order))
            .all()
        )
        chunk_by_id = {c.id: c for c in chunks}
        return [(chunk_by_id[cid], score_by_id[cid]) for cid in chunk_ids_in_order if cid in chunk_by_id]


_HYBRID_SQL = """
WITH bm25_ranked AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY rank) AS r
    FROM document_chunks_fts
    WHERE document_chunks_fts MATCH :query
    ORDER BY rank
    LIMIT :bm25_k
),
vec_ranked AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY distance) AS r
    FROM document_chunks_vec
    WHERE embedding MATCH :embedding AND k = :vec_k
),
fused AS (
    SELECT chunk_id, SUM(1.0 / (:rrf_k + r)) AS score
    FROM (
        SELECT chunk_id, r FROM bm25_ranked
        UNION ALL
        SELECT chunk_id, r FROM vec_ranked
    )
    GROUP BY chunk_id
)
SELECT f.chunk_id, f.score
FROM fused f
JOIN document_chunks c ON c.id = f.chunk_id
JOIN documents d ON d.id = c.document_id
WHERE d.vehicle_id = :vehicle_id
  AND d.processing_status = 'ready'
  AND c.id NOT IN :exclude_ids
ORDER BY f.score DESC
LIMIT :result_k
"""
```

- [ ] **Step 4: Run the tests — debug FTS5 query syntax if needed**

Run: `uv run pytest tests/test_services/test_hybrid_retrieval_service.py -v`

Expected: 5 PASS.

If you get `fts5: syntax error near "?"` it means the FTS5 MATCH parameter binding tripped on a special character. The test queries are all alphanumeric so this should not happen. If it does, sanitize the query: `query_text = " ".join(re.findall(r"\w+", query))` before binding.

If you get `vec0: invalid argument: k must be a positive integer`, ensure the `:vec_k` bind is positional: sqlite-vec requires `k` to be a literal-or-positional integer in the same constraint.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add app/services/hybrid_retrieval_service.py tests/test_services/test_hybrid_retrieval_service.py
git commit -m "feat: add HybridRetrievalService with RRF over BM25 + vec0"
```

---

## Task 5: Sanitize FTS5 query syntax

**Files:**
- Modify: `app/services/hybrid_retrieval_service.py`
- Modify: `tests/test_services/test_hybrid_retrieval_service.py`

User questions contain question marks, quotes, and operators that FTS5 treats as syntax (`AND`, `OR`, `NEAR`, `:`, `"`). We need to convert the query to an OR-of-tokens before binding.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_hybrid_retrieval_service.py`:

```python
def test_retrieve_handles_question_marks_and_punctuation(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    # Punctuation and an FTS5 keyword in the query.
    results = svc.retrieve(query="What is the head bolt torque?", vehicle_id=v1.id)
    contents = [c.content for c, _ in results]
    assert "Cylinder head bolt torque is 129 Nm" in contents


def test_retrieve_handles_query_with_only_punctuation_returns_empty(db_session, vehicle_with_corpus):
    v1, _ = vehicle_with_corpus
    svc = _make_service(db_session)
    # Pure punctuation has no FTS5 tokens; vec_ranked may still match. The
    # service should not raise — it should return whatever vector found.
    results = svc.retrieve(query="???", vehicle_id=v1.id)
    # Don't assert exact contents; just no exception.
    assert isinstance(results, list)
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_services/test_hybrid_retrieval_service.py -v -k handles_question`
Expected: likely FAIL with FTS5 syntax error.

- [ ] **Step 3: Sanitize before bind**

In `app/services/hybrid_retrieval_service.py`, add a helper and call it before binding `:query`:

```python
import re

_FTS5_TOKEN = re.compile(r"\w+", re.UNICODE)


def _to_fts5_query(query: str) -> str:
    """Convert free-form text to an FTS5 OR query of bare tokens.

    Strips quotes, punctuation, and operators. Returns an empty string when
    the query has no alphanumeric content — callers must treat that as
    'BM25 contributes nothing' rather than 'syntax error'.
    """
    tokens = _FTS5_TOKEN.findall(query)
    return " OR ".join(tokens)
```

Update `retrieve()` to compute the sanitized FTS5 query and skip the BM25 path entirely when it's empty:

```python
def retrieve(
    self,
    query: str,
    vehicle_id: int,
    exclude_chunk_ids: frozenset[int] = frozenset(),
) -> list[tuple[DocumentChunk, float]]:
    fts_query = _to_fts5_query(query)
    query_emb = self._embedding.embed_query(query)
    emb_blob = struct.pack(f"{len(query_emb)}f", *query_emb)

    sql = text(_HYBRID_SQL_WITH_BM25 if fts_query else _HYBRID_SQL_VEC_ONLY)
    sql = sql.bindparams(bindparam("exclude_ids", expanding=True))

    params = {
        "embedding": emb_blob,
        "vehicle_id": vehicle_id,
        "vec_k": self._vector_top_k,
        "rrf_k": self._rrf_k,
        "result_k": self._result_top_k,
        "exclude_ids": list(exclude_chunk_ids) or [-1],
    }
    if fts_query:
        params["query"] = fts_query
        params["bm25_k"] = self._bm25_top_k

    rows = self._session.execute(sql, params).fetchall()
    if not rows:
        return []

    chunk_ids_in_order = [row[0] for row in rows]
    score_by_id = {row[0]: float(row[1]) for row in rows}
    chunks = (
        self._session.query(DocumentChunk)
        .filter(DocumentChunk.id.in_(chunk_ids_in_order))
        .all()
    )
    chunk_by_id = {c.id: c for c in chunks}
    return [(chunk_by_id[cid], score_by_id[cid]) for cid in chunk_ids_in_order if cid in chunk_by_id]
```

Rename the existing SQL constant to `_HYBRID_SQL_WITH_BM25` and add a vector-only variant:

```python
_HYBRID_SQL_WITH_BM25 = """
WITH bm25_ranked AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY rank) AS r
    FROM document_chunks_fts
    WHERE document_chunks_fts MATCH :query
    ORDER BY rank
    LIMIT :bm25_k
),
vec_ranked AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY distance) AS r
    FROM document_chunks_vec
    WHERE embedding MATCH :embedding AND k = :vec_k
),
fused AS (
    SELECT chunk_id, SUM(1.0 / (:rrf_k + r)) AS score
    FROM (
        SELECT chunk_id, r FROM bm25_ranked
        UNION ALL
        SELECT chunk_id, r FROM vec_ranked
    )
    GROUP BY chunk_id
)
SELECT f.chunk_id, f.score
FROM fused f
JOIN document_chunks c ON c.id = f.chunk_id
JOIN documents d ON d.id = c.document_id
WHERE d.vehicle_id = :vehicle_id
  AND d.processing_status = 'ready'
  AND c.id NOT IN :exclude_ids
ORDER BY f.score DESC
LIMIT :result_k
"""

_HYBRID_SQL_VEC_ONLY = """
WITH vec_ranked AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY distance) AS r
    FROM document_chunks_vec
    WHERE embedding MATCH :embedding AND k = :vec_k
)
SELECT v.chunk_id, 1.0 / (:rrf_k + v.r) AS score
FROM vec_ranked v
JOIN document_chunks c ON c.id = v.chunk_id
JOIN documents d ON d.id = c.document_id
WHERE d.vehicle_id = :vehicle_id
  AND d.processing_status = 'ready'
  AND c.id NOT IN :exclude_ids
ORDER BY score DESC
LIMIT :result_k
"""
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_services/test_hybrid_retrieval_service.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/hybrid_retrieval_service.py tests/test_services/test_hybrid_retrieval_service.py
git commit -m "fix: sanitize FTS5 query and fall back to vec-only when no tokens"
```

---

## Task 6: Delete the old retrieval module + similarity helper

**Files:**
- Delete: `app/services/retrieval_service.py`
- Delete: `app/rag/similarity.py`
- Delete: `tests/test_services/test_retrieval_service.py`
- Delete: `tests/test_rag/test_similarity.py`

These files were skipped by Plan 1 and are now superseded.

- [ ] **Step 1: Confirm nothing imports them anymore**

Run:
```bash
grep -rn "retrieval_service\|RetrievalService" app/ tests/
grep -rn "rag.similarity\|rank_chunks\|cosine_similarity" app/ tests/
```

Expected: matches only inside the files we're about to delete (and the `chat_service.py`/`test_chat_service.py` which are still on disk but skipped — Plan 3 deletes them).

If `app/services/chat_service.py` still imports `RetrievalService`, leave it for now: Plan 3's first task replaces `ChatService` entirely. The skipped test means CI is green; the runtime CLI is broken right now (the chat command tries to import a deleted module), which is acceptable mid-feature on this branch.

Actually — to keep `mechanic-sidekick chat` from crashing during this plan, leave `retrieval_service.py` on disk *temporarily* and instead make Plan 3's first task delete both `chat_service.py` and `retrieval_service.py` together. So **skip Step 2-4 below**; instead:

- [ ] **Step 2: Delete only the test files**

```bash
git rm tests/test_services/test_retrieval_service.py
git rm tests/test_rag/test_similarity.py
```

- [ ] **Step 3: Delete the unused similarity module**

`app/rag/similarity.py` is imported only by `retrieval_service.py`. Both go in Plan 3's Task 1. Leave them for now.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/ -v`
Expected: green; no skipped tests for retrieval/similarity (because we deleted them).

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: remove obsolete retrieval/similarity tests (services deleted in Plan 3)"
```

---

## Task 7: First-run download of the reranker model

**Goal:** Verify `BgeReranker` loads the real model on this machine. Manual smoke test — no code changes.

- [ ] **Step 1: Trigger the download**

Run:
```bash
uv run python -c "
from app.services.reranker import BgeReranker
from app.models.document_chunk import DocumentChunk

reranker = BgeReranker(model_name='BAAI/bge-reranker-v2-m3')
chunks = [
    DocumentChunk(document_id=1, chunk_index=0, content='Cylinder head bolt torque is 129 Nm'),
    DocumentChunk(document_id=1, chunk_index=1, content='Brake fluid is DOT 4'),
    DocumentChunk(document_id=1, chunk_index=2, content='Wheel bolt torque is 120 Nm'),
]
out = reranker.rerank(query='head bolt torque', candidates=chunks, top_k=2)
for c, s in out:
    print(f'{s:.3f}  {c.content}')
"
```

Expected on first run: prints download progress (~500MB to `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/`), then prints two lines. The cylinder head chunk should score notably higher than the brake fluid chunk.

Subsequent runs are offline — model loaded from the HF cache.

- [ ] **Step 2: No commit**

Verification only. Move on.

---

## Self-Review Checklist (run before marking Plan 2 done)

- [ ] Spec section 3 (retrieval pipeline) — covered? Hybrid retrieval (Task 4) + cross-encoder rerank (Task 3) + Reranker protocol with IdentityReranker for unit tests (Task 2). RRF k=60 default is configurable (Task 1).
- [ ] Performance target — single SQL CTE for the candidate pull. Reranker called once per retrieval call. Plan 3's loop will call retrieve at most 3 times → ~600ms retrieval cost as the spec predicted.
- [ ] BM25 + vec0 mirror Plan 1's invariants (chunk_id matches `document_chunks.id`).
- [ ] FTS5 query sanitization (Task 5) so user questions don't trip the parser.
- [ ] No placeholders, no ungrounded type names. `Reranker` Protocol → `BgeReranker` (real) + `IdentityReranker` (test). `HybridRetrievalService.retrieve(query, vehicle_id, exclude_chunk_ids)` matches the spec's signature.
- [ ] `app/services/retrieval_service.py` and `app/rag/similarity.py` are *intentionally* still on disk — Plan 3 deletes them together with `ChatService`.
