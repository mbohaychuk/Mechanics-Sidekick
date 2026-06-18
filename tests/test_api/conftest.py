import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app, configure_db


@pytest.fixture
def api_client(tmp_path):
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as client:
        yield client
