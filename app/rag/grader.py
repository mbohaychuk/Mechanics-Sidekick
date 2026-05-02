# app/rag/grader.py
"""LLM graders for the agentic loop.

Both graders use a small fast model (gemma4:e4b) and structured JSON output.
Failure semantics differ:
  - RelevanceGrader fails OPEN: malformed output -> assume relevant. Better
    to send a candidate to generation than to lose it; groundedness catches
    bad answers.
  - GroundednessGrader fails CLOSED: malformed output -> treat as not
    grounded. Better to trigger a regeneration than to ship a fabrication.
"""
import json
import re
from dataclasses import dataclass

from app.models.document_chunk import DocumentChunk
from app.models.vehicle import Vehicle
from app.rag.loop_state import GradingResult
from app.services.ollama_service import OllamaService


_VARIANT_TOKEN = re.compile(r"\b(4\.2L|6\.0L|5\.2L|W12)\b", re.IGNORECASE)


@dataclass
class GroundednessResult:
    grounded: bool
    unsupported_claims: list[str]
    reason: str


# --- RelevanceGrader -----------------------------------------------------------


class RelevanceGrader:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def grade(
        self,
        chunk: DocumentChunk,
        question: str,
        vehicle: Vehicle,
    ) -> GradingResult:
        # Hard side of Q6: if chunk has a tagged variant and vehicle's engine
        # token implies a different variant, reject locally without an LLM call.
        vehicle_variant = _extract_variant(vehicle.engine)
        chunk_variant = (chunk.engine_variant or "").strip()
        if (
            chunk_variant
            and chunk_variant.lower() not in ("both",)
            and vehicle_variant is not None
            and chunk_variant != vehicle_variant
        ):
            return GradingResult(
                chunk=chunk,
                relevant=False,
                reason=f"engine variant mismatch: chunk={chunk_variant}, vehicle={vehicle_variant}",
            )

        prompt = self._build_prompt(chunk, question, vehicle)
        for attempt in range(2):
            response = self._ollama.chat(
                [{"role": "user", "content": prompt}], self._model
            )
            parsed = _parse_json(response)
            if parsed is not None and "relevant" in parsed:
                return GradingResult(
                    chunk=chunk,
                    relevant=bool(parsed["relevant"]),
                    reason=str(parsed.get("reason", "")),
                )
            prompt = self._strict_retry_prompt(chunk, question, vehicle)

        # Fail-open per spec.
        return GradingResult(
            chunk=chunk,
            relevant=True,
            reason="grader output malformed; failing open",
        )

    @staticmethod
    def _build_prompt(chunk: DocumentChunk, question: str, vehicle: Vehicle) -> str:
        return (
            "You judge whether a service-manual excerpt is relevant to a mechanic's question.\n\n"
            f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}\n"
            f"Chunk engine_variant tag: {chunk.engine_variant or 'none'}\n"
            f"Chunk section: {chunk.section_title or 'unknown'}\n\n"
            f"Question: {question}\n\n"
            "Excerpt:\n"
            f"{chunk.content[:1500]}\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"relevant": true | false, "reason": "<one sentence>"}\n'
            "An excerpt is relevant only if it directly answers the question for "
            f"this specific vehicle's engine ({vehicle.engine})."
        )

    @staticmethod
    def _strict_retry_prompt(chunk: DocumentChunk, question: str, vehicle: Vehicle) -> str:
        return (
            "Your previous response was not valid JSON. Reply with EXACTLY one line "
            "matching this format and nothing else:\n"
            '{"relevant": true, "reason": "..."}\n\n'
            f"Vehicle engine: {vehicle.engine}. Question: {question}\n"
            f"Excerpt: {chunk.content[:800]}"
        )


# --- GroundednessGrader --------------------------------------------------------


class GroundednessGrader:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def grade(
        self,
        answer: str,
        chunks: list[DocumentChunk],
    ) -> GroundednessResult:
        prompt = self._build_prompt(answer, chunks)
        for attempt in range(2):
            response = self._ollama.chat(
                [{"role": "user", "content": prompt}], self._model
            )
            parsed = _parse_json(response)
            if parsed is not None and "grounded" in parsed:
                claims = parsed.get("unsupported_claims", []) or []
                if not isinstance(claims, list):
                    claims = [str(claims)]
                return GroundednessResult(
                    grounded=bool(parsed["grounded"]),
                    unsupported_claims=[str(c) for c in claims],
                    reason=str(parsed.get("reason", "")),
                )
            prompt = self._strict_retry_prompt(answer)

        # Fail-closed per spec.
        return GroundednessResult(
            grounded=False,
            unsupported_claims=[],
            reason="grader output malformed; failing closed",
        )

    @staticmethod
    def _build_prompt(answer: str, chunks: list[DocumentChunk]) -> str:
        excerpts = "\n\n".join(
            f"[{i + 1}] {c.content[:800]}" for i, c in enumerate(chunks)
        )
        return (
            "You verify that an answer is supported by service-manual excerpts.\n\n"
            "Excerpts:\n"
            f"{excerpts}\n\n"
            f"Answer to verify:\n{answer}\n\n"
            "Reply with a single JSON object on one line:\n"
            '{"grounded": true | false, "unsupported_claims": ["..."], "reason": "<one sentence>"}\n'
            "An answer is grounded only if every factual claim in it is directly "
            "supported by at least one excerpt. Unsupported_claims lists each "
            "claim in the answer that is not supported, or empty if grounded."
        )

    @staticmethod
    def _strict_retry_prompt(answer: str) -> str:
        return (
            "Your previous response was not valid JSON. Reply with EXACTLY one line:\n"
            '{"grounded": true, "unsupported_claims": [], "reason": "..."}\n\n'
            f"Answer to verify: {answer[:1500]}"
        )


# --- Helpers -------------------------------------------------------------------


def _extract_variant(engine_field: str) -> str | None:
    """Pull a canonical variant token (4.2L, 6.0L, etc.) out of free-form vehicle.engine."""
    if not engine_field:
        return None
    match = _VARIANT_TOKEN.search(engine_field)
    if not match:
        return None
    raw = match.group(1).lower()
    return {"4.2l": "4.2L", "6.0l": "6.0L", "5.2l": "5.2L", "w12": "W12"}[raw]


def _parse_json(text: str) -> dict | None:
    """Best-effort: extract the first JSON object from free-form LLM output."""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
