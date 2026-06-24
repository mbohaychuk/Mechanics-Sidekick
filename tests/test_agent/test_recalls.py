from unittest.mock import MagicMock

from app.agent.recalls_client import NhtsaRecallsClient
from app.agent.tools import GET_RECALLS_TOOL, execute_get_recalls


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttp:
    """Stands in for an httpx.Client: records calls, returns canned JSON per (url, params)."""

    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    def get(self, url, params=None):
        self.calls.append((url, params))
        return _FakeResponse(self._responder(url, params))


# ---- NhtsaRecallsClient ----------------------------------------------------


def test_recalls_by_vehicle_returns_parsed_results():
    http = _FakeHttp(
        lambda url, params: {
            "Count": 1,
            "results": [{"NHTSACampaignNumber": "18V894000", "Component": "ENGINE"}],
        }
    )
    client = NhtsaRecallsClient(http_client=http)

    out = client.recalls_by_vehicle(2015, "Ford", "F-150")

    assert len(out) == 1
    assert out[0]["NHTSACampaignNumber"] == "18V894000"
    url, params = http.calls[0]
    assert url.endswith("/recalls/recallsByVehicle")
    assert params == {"make": "Ford", "model": "F-150", "modelYear": 2015}


def test_recalls_by_vehicle_returns_empty_when_no_results():
    http = _FakeHttp(lambda url, params: {"Count": 0, "results": []})
    client = NhtsaRecallsClient(http_client=http)

    assert client.recalls_by_vehicle(2015, "Ford", "F-150") == []


# ---- execute_get_recalls ---------------------------------------------------


def test_get_recalls_tool_schema():
    assert GET_RECALLS_TOOL["type"] == "function"
    fn = GET_RECALLS_TOOL["function"]
    assert fn["name"] == "get_recalls"
    # No required inputs — the vehicle identity comes from the server, not the model.
    assert fn["parameters"]["properties"] == {}
    assert fn["parameters"].get("required", []) == []


def test_execute_get_recalls_formats_campaigns_and_sources():
    client = MagicMock()
    client.recalls_by_vehicle.return_value = [
        {
            "NHTSACampaignNumber": "18V894000",
            "Component": "POWER TRAIN:AUTOMATIC TRANSMISSION",
            "ReportReceivedDate": "18/12/2018",
            "Summary": "may unexpectedly downshift",
            "Consequence": "increases the risk of a crash",
            "Remedy": "dealers will reprogram the powertrain control module",
        }
    ]

    out = execute_get_recalls(client, 2015, "Ford", "F-150")

    client.recalls_by_vehicle.assert_called_once_with(2015, "Ford", "F-150")
    assert "18V894000" in out["model_text"]
    assert "AUTOMATIC TRANSMISSION" in out["model_text"]
    assert "reprogram the powertrain" in out["model_text"]
    assert out["sources"][0]["kind"] == "recall"
    assert out["sources"][0]["campaign"] == "18V894000"


def test_execute_get_recalls_none_found():
    client = MagicMock()
    client.recalls_by_vehicle.return_value = []

    out = execute_get_recalls(client, 2015, "Ford", "F-150")

    assert out["sources"] == []
    assert "no open" in out["model_text"].lower()
    assert "F-150" in out["model_text"]


def test_execute_get_recalls_service_error_degrades_gracefully():
    client = MagicMock()
    client.recalls_by_vehicle.side_effect = RuntimeError("network down")

    out = execute_get_recalls(client, 2015, "Ford", "F-150")

    assert out["sources"] == []
    assert "network down" not in out["model_text"]  # raw error must not leak
    assert "could not" in out["model_text"].lower()
