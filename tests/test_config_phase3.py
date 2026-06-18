from app.config import Settings


def test_phase3_settings_defaults():
    s = Settings(_env_file=None)
    assert s.obd_mcp_enabled is False
    assert s.obd_mcp_dir == ""
    assert s.obd_port == "socket://localhost:35000"
    assert s.obd_tool_denylist == "ping,record_session"
    assert s.mcp_call_timeout_s == 30.0
    assert s.mcp_start_timeout_s == 20.0
    assert s.web_search_enabled is True
    assert s.tavily_api_key == ""
    assert s.web_search_max_results == 5
