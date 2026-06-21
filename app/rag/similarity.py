# app/rag/similarity.py
import json
import numpy as np


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Return cosine similarity in [-1.0, 1.0]; returns 0.0 if either vector is zero
    or the two vectors have different dimensions (e.g. a heterogeneous corpus after an
    embed-model/provider swap) — degrade rather than raise deep in the retrieval path."""
    if len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a, dtype=np.float64)
    b = np.array(vec_b, dtype=np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def rank_chunks(query_vec: list[float], chunks: list, top_k: int) -> list[tuple]:
    """Score each chunk against the query vector and return top_k sorted descending."""
    scored = [
        (chunk, cosine_similarity(query_vec, json.loads(chunk.embedding_json)))
        for chunk in chunks
        if chunk.embedding_json is not None
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def rank_fusion(cosine_scored: list[tuple], bm25_ids: list[int], k: int = 60) -> list[tuple]:
    """Fuse a cosine-ranked list of (chunk, cosine) with a BM25-ranked list of chunk ids by
    Reciprocal Rank Fusion (RRF). Returns the SAME (chunk, cosine) tuples reordered by fused
    score — the cosine rides along so the (chunk, score) contract is preserved. A chunk absent
    from the BM25 list simply gets no BM25 term. Stable: ties keep the cosine order."""
    bm25_rank = {cid: rank for rank, cid in enumerate(bm25_ids)}
    fused = []
    for cosine_rank, (chunk, cosine) in enumerate(cosine_scored):
        score = 1.0 / (k + cosine_rank + 1)
        bm25 = bm25_rank.get(chunk.id)
        if bm25 is not None:
            score += 1.0 / (k + bm25 + 1)
        fused.append((chunk, cosine, score))
    fused.sort(key=lambda item: item[2], reverse=True)
    return [(chunk, cosine) for chunk, cosine, _ in fused]
