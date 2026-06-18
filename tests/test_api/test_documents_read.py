from app.models.document import Document


def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def test_list_and_get_document(api_client):
    vid = _make_vehicle(api_client)

    # Seed a document row directly through the app's session factory.
    factory = api_client.app.state.session_factory
    session = factory()
    doc = Document(vehicle_id=vid, file_name="m.pdf", stored_path="/x/m.pdf")
    session.add(doc)
    session.commit()
    doc_id = doc.id
    session.close()

    listed = api_client.get(f"/api/vehicles/{vid}/documents")
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [doc_id]
    assert listed.json()[0]["processing_status"] == "pending"

    got = api_client.get(f"/api/documents/{doc_id}")
    assert got.status_code == 200
    assert got.json()["file_name"] == "m.pdf"


def test_get_missing_document_is_404(api_client):
    assert api_client.get("/api/documents/999").status_code == 404
