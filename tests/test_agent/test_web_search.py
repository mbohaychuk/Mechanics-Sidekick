from unittest.mock import MagicMock

from app.agent.tools import WEB_SEARCH_TOOL, execute_web_search


def test_web_search_tool_schema():
    assert WEB_SEARCH_TOOL["type"] == "function"
    fn = WEB_SEARCH_TOOL["function"]
    assert fn["name"] == "web_search"
    assert "query" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["query"]


def test_execute_web_search_formats_answer_and_results():
    client = MagicMock()
    client.search.return_value = {
        "answer": "Torque is 40 Nm.",
        "results": [
            {"title": "Forum thread", "url": "http://example.com/a", "content": "snippet text"}
        ],
    }

    result = execute_web_search(client, "brake torque", max_results=3)

    client.search.assert_called_once_with(
        query="brake torque", include_answer=True, search_depth="basic", max_results=3
    )
    assert result["sources"] == []
    assert "Torque is 40 Nm." in result["model_text"]
    assert "http://example.com/a" in result["model_text"]
    assert "snippet text" in result["model_text"]


def test_execute_web_search_empty():
    client = MagicMock()
    client.search.return_value = {"answer": None, "results": []}
    result = execute_web_search(client, "x")
    assert result["sources"] == []
    assert "No relevant web results" in result["model_text"]
