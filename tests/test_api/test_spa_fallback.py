import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app, configure_db
from app.config import settings


@pytest.fixture
def spa_client(tmp_path, monkeypatch):
    spa = tmp_path / "dist"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><div id='app'></div>")
    (spa / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr(settings, "spa_dist_dir", str(spa))
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as client:
        yield client


def test_spa_deep_link_refresh_serves_index_html(spa_client):
    # A hard refresh / bookmark of a history-mode client route must return the SPA, not a 404.
    r = spa_client.get("/vehicles/3/diagnostic")
    assert r.status_code == 200
    assert "id='app'" in r.text


def test_spa_serves_existing_assets(spa_client):
    assert spa_client.get("/assets/app.js").status_code == 200


def test_spa_fallback_does_not_mask_unknown_api_404(spa_client):
    # Unknown API paths must still 404 (JSON), not silently return index.html.
    r = spa_client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "id='app'" not in r.text


def test_spa_fallback_serves_client_routes_that_merely_start_with_api(spa_client):
    # A client route like /apiary must load the SPA — only real /api/* routes should 404.
    r = spa_client.get("/apiary")
    assert r.status_code == 200
    assert "id='app'" in r.text
