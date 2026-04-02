import json
import numpy as np


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
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
