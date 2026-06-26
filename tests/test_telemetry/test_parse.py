import json

import pytest

from app.telemetry.parse import (
    LiveReadError,
    parse_dtcs,
    parse_live_data,
    parse_supported_pids,
    parse_vin,
)


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


def test_parse_live_data_handles_ndjson_from_multiblock_tool_result():
    # read_live_data returns a LIST, which the MCP host serializes as one content block per row
    # and joins with newlines — so the payload is several concatenated JSON objects (NDJSON), not
    # a single JSON array. The parser must decode all of them, compact OR pretty-printed.
    rows = [
        {"pid": "0C", "name": "RPM", "value": 978, "unit": "rpm", "error": None},
        {"pid": "05", "name": "COOLANT_TEMP", "value": 72, "unit": "C", "error": None},
        {"pid": "10", "name": "MAF", "value": None, "unit": None, "error": "NOT_SUPPORTED"},
    ]
    out = parse_live_data("\n".join(json.dumps(r) for r in rows))
    assert out["RPM"] == {"value": 978, "unit": "rpm"}
    assert out["COOLANT_TEMP"] == {"value": 72, "unit": "C"}
    assert out["MAF"] is None

    out_pretty = parse_live_data("\n".join(json.dumps(r, indent=2) for r in rows))
    assert out_pretty["RPM"] == {"value": 978, "unit": "rpm"}


def test_parse_live_data_handles_a_single_reading_object():
    out = parse_live_data(json.dumps({"pid": "0C", "name": "RPM", "value": 978, "unit": "rpm", "error": None}))
    assert out["RPM"] == {"value": 978, "unit": "rpm"}


def test_parse_live_data_raises_on_host_sentinel():
    # Host sentinels start with "[" but are NOT valid JSON — must be distinguished by json.loads, not prefix.
    for sentinel in ["[obd unavailable] ...", "[tool error] read_live_data: boom", "[obd error] nope"]:
        with pytest.raises(LiveReadError):
            parse_live_data(sentinel)


def test_parse_dtcs_returns_normalized_codes():
    # read_dtcs returns a single envelope dict {scope, count, codes:[...], timestamp}.
    text = json.dumps({
        "scope": "all",
        "count": 2,
        "codes": [
            {"code": "P0706", "scope": "stored", "source": "generic",
             "description": "Transmission Range Sensor 'A' Circuit Range/Performance"},
            {"code": "P0707", "scope": "stored", "source": "generic",
             "description": "Transmission Range Sensor 'A' Circuit Low"},
        ],
        "timestamp": 1.0,
    })
    out = parse_dtcs(text)
    assert [c["code"] for c in out] == ["P0706", "P0707"]
    assert out[0] == {"code": "P0706", "scope": "stored", "source": "generic",
                      "description": "Transmission Range Sensor 'A' Circuit Range/Performance"}


def test_parse_dtcs_empty_when_no_codes():
    assert parse_dtcs(json.dumps({"scope": "all", "count": 0, "codes": [], "timestamp": 1.0})) == []


def test_parse_dtcs_raises_on_host_sentinel():
    # A read failure must be distinguishable from a genuine "no codes" — so a sentinel raises
    # (the manager turns that into an "unavailable", never a fabricated all-clear).
    with pytest.raises(LiveReadError):
        parse_dtcs("[obd unavailable] The OBD tool server is not running.")


def test_parse_supported_pids_and_vin():
    pids = parse_supported_pids(json.dumps([{"pid": "0C", "name": "RPM", "description": "Engine RPM"}]))
    assert pids[0]["name"] == "RPM"
    assert parse_vin(json.dumps({"vin": "WAUZZZ", "protocol": "ISO 15765-4"})) == "WAUZZZ"
    assert parse_vin(json.dumps({"vin": None})) is None
    with pytest.raises(LiveReadError):
        parse_vin("[obd unavailable] x")
