# app/services/hybrid_retrieval_service.py
"""Two-retriever fusion: BM25 (FTS5) + cosine (sqlite-vec) → RRF → top-K.

A single SQL CTE pulls per-retriever top-K candidates, fuses them via
Reciprocal Rank Fusion (score = sum(1.0 / (rrf_k + rank_i))), and joins
document_chunks to scope by vehicle and exclude rejected chunk ids.

This is the spec's stage-1 retriever; downstream callers rerank the result
to top-10 with a cross-encoder.
"""
import sqlite_vec
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
        emb_blob = sqlite_vec.serialize_float32(query_emb)

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
