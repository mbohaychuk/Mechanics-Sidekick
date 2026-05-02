# app/rag/query_rewriter.py
"""LLM-driven query rewriter for the agentic loop.

Conditions on the IMMUTABLE original question plus a list of prior failure
reasons; never on the previous rewrite. This is a deliberate design choice
from the spec to prevent drift across iterations.
"""
from dataclasses import dataclass

from app.models.vehicle import Vehicle
from app.rag.grader import _parse_json
from app.services.ollama_service import OllamaService


@dataclass
class RewriteResult:
    rewritten_query: str
    rationale: str


class QueryRewriter:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def rewrite(
        self,
        original_question: str,
        vehicle: Vehicle,
        prior_failure_reasons: list[str],
    ) -> RewriteResult:
        reasons_text = "\n".join(f"- {r}" for r in prior_failure_reasons) or "- (none)"
        prompt = (
            "You rewrite a mechanic's question to retrieve better service-manual excerpts.\n\n"
            f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}\n\n"
            f"Original question:\n{original_question}\n\n"
            "Why the previous retrieval failed:\n"
            f"{reasons_text}\n\n"
            "Rewrite the question to be more specific to this vehicle and engine. "
            "Add manufacturer code, system names, or technical synonyms that appear in OEM manuals. "
            "Do NOT invent specifications. Stay tied to the original question's intent.\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"rewritten_query": "...", "rationale": "<one sentence>"}'
        )
        response = self._ollama.chat([{"role": "user", "content": prompt}], self._model)
        parsed = _parse_json(response)
        if parsed and "rewritten_query" in parsed:
            return RewriteResult(
                rewritten_query=str(parsed["rewritten_query"]),
                rationale=str(parsed.get("rationale", "")),
            )
        return RewriteResult(
            rewritten_query=original_question,
            rationale="rewriter output malformed; reusing original question",
        )
