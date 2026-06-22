"""Load + validate the labeled golden-question set for the RAG eval harness.

Each question targets its answer by `answer_contains` (substrings a relevant chunk must hold —
used for DTC codes / spec values) and/or `relevant_pages` (a page cluster — used for multi-page
procedures). At least one is required. Fails fast on malformed gold, since a silently wrong
label set would make every downstream metric lie.
"""
import json
from pathlib import Path

VALID_TYPES = {"exact_token", "conceptual", "paraphrase", "table_lookup"}


def load_golden(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("golden set must be a JSON list of questions")
    for i, item in enumerate(data):
        for field in ("id", "question", "type"):
            if field not in item:
                raise ValueError(f"golden item {i} missing required field '{field}'")
        if item["type"] not in VALID_TYPES:
            raise ValueError(f"golden item {item['id']!r} has unknown type {item['type']!r}")
        answer_contains = item.get("answer_contains") or []
        relevant_pages = item.get("relevant_pages") or []
        if not answer_contains and not relevant_pages:
            raise ValueError(f"golden item {item['id']!r} needs answer_contains or relevant_pages")
        if answer_contains and not all(isinstance(s, str) and s for s in answer_contains):
            raise ValueError(f"golden item {item['id']!r} answer_contains must be non-empty strings")
        if relevant_pages and not all(isinstance(p, int) for p in relevant_pages):
            raise ValueError(f"golden item {item['id']!r} relevant_pages must be integers")
    return data
