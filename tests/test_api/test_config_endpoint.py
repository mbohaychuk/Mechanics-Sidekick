def test_config_reports_non_secret_status(api_client):
    r = api_client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "openai_key_present",
        "obd_mcp_enabled",
        "obd_port",
        "web_search_enabled",
        "web_search_key_present",
        "chat_model",
        "embed_model",
    }
    assert isinstance(body["openai_key_present"], bool)
    assert body["obd_port"]  # non-empty default
    # Never leak the actual secret values.
    assert "sk-" not in str(body)
