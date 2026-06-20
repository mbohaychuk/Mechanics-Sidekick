import json

import pytest

from app.telemetry.parse import LiveReadError, parse_live_data, parse_supported_pids, parse_vin


def test_parse_live_data_maps_names_to_value_unit():
    text = json.dumps([
        {"pid": "0C", "name": "RPM", "value": 820, "unit": "revolutions_per_minute", "timestamp": 1.0},
        {"pid": "0D", "name": "SPEED", "value": 0, "unit": "kph", "timestamp": 1.0},
    ])
    out = parse_live_data(text)
    assert out == {
        "RPM": {"value": 820, "unit": "revolutions_per_minute"},
        "SPEED": {"value": 0, "unit": "kph"},
    }


def test_parse_live_data_error_markers_become_none():
    text = json.dumps([
        {"pid": "0C", "name": "RPM", "value": 820, "unit": "rpm", "timestamp": 1.0},
        {"pid": "05", "name": "COOLANT_TEMP", "error": "NOT_SUPPORTED", "timestamp": 1.0},
    ])
    out = parse_live_data(text)
    assert out["RPM"]["value"] == 820
    assert out["COOLANT_TEMP"] is None


def test_parse_live_data_real_obd_mcp_shape_success_rows_carry_null_error_key():
    # The real obd-mcp `_live_entry` ALWAYS includes an "error" key (null on success);
    # the parser must check the error VALUE, not key presence, or it discards every reading.
    text = json.dumps([
        {"pid": "0C", "name": "RPM", "value": 820, "unit": "rpm", "error": None, "timestamp": 1.0},
        {"pid": "05", "name": "COOLANT_TEMP", "value": None, "unit": None, "error": "NO_DATA", "timestamp": 1.0},
    ])
    out = parse_live_data(text)
    assert out["RPM"] == {"value": 820, "unit": "rpm"}
    assert out["COOLANT_TEMP"] is None


def test_parse_live_data_raises_on_host_sentinel():
    # Host sentinels start with "[" but are NOT valid JSON — must be distinguished by json.loads, not prefix.
    for sentinel in ["[obd unavailable] ...", "[tool error] read_live_data: boom", "[obd error] nope"]:
        with pytest.raises(LiveReadError):
            parse_live_data(sentinel)


def test_parse_supported_pids_and_vin():
    pids = parse_supported_pids(json.dumps([{"pid": "0C", "name": "RPM", "description": "Engine RPM"}]))
    assert pids[0]["name"] == "RPM"
    assert parse_vin(json.dumps({"vin": "WAUZZZ", "protocol": "ISO 15765-4"})) == "WAUZZZ"
    assert parse_vin(json.dumps({"vin": None})) is None
    with pytest.raises(LiveReadError):
        parse_vin("[obd unavailable] x")
