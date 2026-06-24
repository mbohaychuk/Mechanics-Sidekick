import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import create_app, configure_db


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    # API tests must never spawn the external obd-mcp host: it depends on a developer's local
    # .env (OBD_MCP_ENABLED) and its async stdio teardown is not TestClient/anyio-safe, which
    # fails the suite whenever OBD is enabled for live use. Force it off for hermetic tests.
    monkeypatch.setattr(main.settings, "obd_mcp_enabled", False)
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as client:
        yield client
