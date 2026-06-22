from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agent.tools import SEARCH_MANUALS_TOOL, execute_search_manuals


def test_tool_schema_shape():
    assert SEARCH_MANUALS_TOOL["type"] == "function"
    fn = SEARCH_MANUALS_TOOL["function"]
    assert fn["name"] == "search_manuals"
    assert "query" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["query"]
    # the agent routes by tagging each search with an intent (lookup vs procedure)
    assert fn["parameters"]["properties"]["intent"]["enum"] == ["lookup", "procedure"]


def test_execute_maps_chunks_to_sources_and_text():
    chunk = SimpleNamespace(document_id=7, page_number=42, content="Torque is 40 Nm.")
    retrieval = MagicMock()
    retrieval.retrieve.return_value = [(chunk, 0.91234)]
    doc_repo = MagicMock()
    doc_repo.get_by_id.return_value = SimpleNamespace(file_name="manual.pdf")

    result = execute_search_manuals(retrieval, doc_repo, vehicle_id=1, query="torque")

    retrieval.retrieve.assert_called_once_with(vehicle_id=1, question="torque", mode="auto")
    assert result["sources"] == [{"filename": "manual.pdf", "page": 42, "score": 0.9123}]
    assert "manual.pdf" in result["model_text"]
    assert "Torque is 40 Nm." in result["model_text"]


def test_execute_routes_intent_to_retrieval_mode():
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    execute_search_manuals(retrieval, MagicMock(), vehicle_id=1, query="oil capacity", intent="lookup")
    retrieval.retrieve.assert_called_once_with(vehicle_id=1, question="oil capacity", mode="lookup")

    retrieval.reset_mock()
    execute_search_manuals(retrieval, MagicMock(), vehicle_id=1, query="replace thermostat", intent="procedure")
    retrieval.retrieve.assert_called_once_with(vehicle_id=1, question="replace thermostat", mode="procedure")


def test_execute_unknown_intent_falls_back_to_auto():
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    execute_search_manuals(retrieval, MagicMock(), vehicle_id=1, query="x", intent="banana")
    retrieval.retrieve.assert_called_once_with(vehicle_id=1, question="x", mode="auto")


def test_execute_empty_results():
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    result = execute_search_manuals(retrieval, MagicMock(), vehicle_id=1, query="x")
    assert result["sources"] == []
    assert "No relevant" in result["model_text"]
