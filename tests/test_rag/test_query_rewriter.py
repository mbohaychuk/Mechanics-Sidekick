# tests/test_rag/test_query_rewriter.py
from unittest.mock import MagicMock

from app.models.vehicle import Vehicle
from app.rag.query_rewriter import QueryRewriter, RewriteResult
from app.services.ollama_service import OllamaService


def _vehicle() -> Vehicle:
    return Vehicle(year=2006, make="Audi", model="A8", engine="4.2L V8")


def test_rewriter_returns_rewritten_query_and_rationale():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"rewritten_query": "cylinder head bolt torque sequence 4.2L BFM V8", '
        '"rationale": "added engine code"}'
    )
    rewriter = QueryRewriter(ollama, model="m")
    out = rewriter.rewrite(
        original_question="what is the head bolt torque?",
        vehicle=_vehicle(),
        prior_failure_reasons=["all chunks rejected as engine-variant mismatch"],
    )
    assert isinstance(out, RewriteResult)
    assert "BFM" in out.rewritten_query
    assert out.rationale == "added engine code"


def test_rewriter_prompt_uses_original_question_not_previous_rewrite():
    """Spec: rewriter conditions on the immutable original question."""
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = (
        '{"rewritten_query": "x", "rationale": "y"}'
    )
    rewriter = QueryRewriter(ollama, model="m")
    rewriter.rewrite(
        original_question="ORIGINAL_Q",
        vehicle=_vehicle(),
        prior_failure_reasons=["a", "b"],
    )
    sent = ollama.chat.call_args.args[0][0]["content"]
    assert "ORIGINAL_Q" in sent
    assert "a" in sent and "b" in sent


def test_rewriter_falls_back_to_original_question_on_malformed_output():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "not json"
    rewriter = QueryRewriter(ollama, model="m")
    out = rewriter.rewrite(
        original_question="head bolt torque?",
        vehicle=_vehicle(),
        prior_failure_reasons=[],
    )
    assert out.rewritten_query == "head bolt torque?"
    assert "malformed" in out.rationale.lower()
