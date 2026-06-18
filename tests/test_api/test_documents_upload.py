from unittest.mock import MagicMock

import fitz  # PyMuPDF

from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService


def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def _fake_emb():
    emb = MagicMock(spec=EmbeddingService)
    emb.embed_texts.side_effect = lambda texts: [[0.0, 1.0] for _ in texts]
    return emb


def _fake_ctx():
    ctx = MagicMock(spec=ContextualizationService)
    ctx.generate_context.side_effect = lambda **kwargs: "context summary"
    return ctx


def test_upload_registers_then_processes_to_ready(api_client, monkeypatch, tmp_path):
    vid = _make_vehicle(api_client)

    monkeypatch.setattr("app.api.ingestion.make_embedding_service", lambda s: _fake_emb())
    monkeypatch.setattr(
        "app.api.ingestion.make_contextualization_service", lambda s: _fake_ctx()
    )

    pdf = tmp_path / "manual.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Torque the head bolts to 40 Nm.")
    doc.save(str(pdf))
    doc.close()

    with open(pdf, "rb") as fh:
        r = api_client.post(
            f"/api/vehicles/{vid}/documents",
            files={"file": ("manual.pdf", fh, "application/pdf")},
        )

    assert r.status_code == 202
    body = r.json()
    assert body["processing_status"] == "pending"
    doc_id = body["id"]

    # TestClient runs background tasks before returning, so processing is done.
    final = api_client.get(f"/api/documents/{doc_id}").json()
    assert final["processing_status"] == "ready"
