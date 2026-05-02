# tests/test_rag/test_grader.py
import pytest
from unittest.mock import MagicMock

from app.models.document_chunk import DocumentChunk
from app.models.vehicle import Vehicle
from app.rag.grader import RelevanceGrader, GroundednessGrader
from app.services.ollama_service import OllamaService


def _vehicle(engine: str = "4.2L V8") -> Vehicle:
    return Vehicle(year=2006, make="Audi", model="A8", engine=engine)


def _chunk(content: str, engine_variant: str | None = None) -> DocumentChunk:
    return DocumentChunk(
        document_id=1, chunk_index=0, content=content, engine_variant=engine_variant,
    )


# --- RelevanceGrader -----------------------------------------------------------

def test_relevance_grader_returns_relevant_true_when_llm_says_so():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "answers the question"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("Head bolt torque 129 Nm", "4.2L"), "head bolt torque?", _vehicle("4.2L V8"))
    assert out.relevant is True
    assert out.reason == "answers the question"


def test_relevance_grader_hard_rejects_engine_variant_mismatch_without_calling_llm():
    """Spec Q6: hard side - if chunk variant differs from vehicle, reject locally."""
    ollama = MagicMock(spec=OllamaService)
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Head bolt torque 95 Nm", engine_variant="6.0L"),
        "head bolt torque?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is False
    assert "engine variant mismatch" in out.reason.lower()
    ollama.chat.assert_not_called()


def test_relevance_grader_passes_through_when_chunk_variant_is_null():
    """A chunk with no variant tag (e.g. maintenance schedule) reaches the LLM grader."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "general maintenance applies"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Oil change every 10k miles", engine_variant=None),
        "how often to change oil?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is True


def test_relevance_grader_passes_through_when_chunk_variant_is_both():
    """Spec convention: 'both' applies to either engine."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"relevant": true, "reason": "applies to both"}'
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Spark plug torque 30 Nm", engine_variant="both"),
        "spark plug torque?",
        _vehicle("4.2L V8"),
    )
    assert out.relevant is True


def test_relevance_grader_normalizes_vehicle_engine_token():
    """Vehicle.engine = '4.2L V8 (BFM)' must match chunk.engine_variant = '4.2L'."""
    ollama = MagicMock(spec=OllamaService)
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(
        _chunk("Head bolt torque 95 Nm", engine_variant="6.0L"),
        "head bolt torque?",
        _vehicle("4.2L V8 (BFM)"),
    )
    # Vehicle is 4.2L, chunk is 6.0L → still hard-reject.
    assert out.relevant is False


def test_relevance_grader_fails_open_on_malformed_json():
    """Spec: bad grader output → assume relevant, let groundedness catch it."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ['not json at all', 'still not json']
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("anything"), "q", _vehicle())
    assert out.relevant is True
    assert "malformed" in out.reason.lower()


def test_relevance_grader_retries_once_on_malformed_then_accepts_valid_retry():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = [
        'broken',
        '{"relevant": false, "reason": "wrong topic"}',
    ]
    grader = RelevanceGrader(ollama, model="m")
    out = grader.grade(_chunk("anything"), "q", _vehicle())
    assert out.relevant is False
    assert ollama.chat.call_count == 2


# --- GroundednessGrader --------------------------------------------------------

def test_groundedness_grader_returns_grounded_true_with_empty_claims():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": true, "unsupported_claims": [], "reason": "all supported"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer text", [_chunk("supporting excerpt")])
    assert out.grounded is True
    assert out.unsupported_claims == []


def test_groundedness_grader_returns_unsupported_claims_when_not_grounded():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": false, "unsupported_claims": ["50 Nm spec not in excerpts"], '
        '"reason": "fabricated torque"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer", [_chunk("excerpt")])
    assert out.grounded is False
    assert out.unsupported_claims == ["50 Nm spec not in excerpts"]


def test_groundedness_grader_fails_closed_on_malformed_json():
    """Spec: bad output → treat as not grounded so the loop retries."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.side_effect = ['nope', 'still nope']
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("answer", [_chunk("excerpt")])
    assert out.grounded is False
    assert "malformed" in out.reason.lower()


def test_groundedness_grader_coerces_non_list_claims():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"grounded": false, "unsupported_claims": "single string claim", "reason": "x"}'
    )
    grader = GroundednessGrader(ollama, model="m")
    out = grader.grade("a", [_chunk("c")])
    assert out.unsupported_claims == ["single string claim"]
