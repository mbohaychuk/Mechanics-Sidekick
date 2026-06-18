def test_create_then_get_and_list_vehicle(api_client):
    payload = {
        "year": 2004,
        "make": "Audi",
        "model": "A8",
        "engine": "4.2L V8",
        "vin": None,
        "notes": None,
    }
    created = api_client.post("/api/vehicles", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["id"] >= 1
    assert body["make"] == "Audi"

    vid = body["id"]
    got = api_client.get(f"/api/vehicles/{vid}")
    assert got.status_code == 200
    assert got.json()["model"] == "A8"

    listed = api_client.get("/api/vehicles")
    assert listed.status_code == 200
    assert [v["id"] for v in listed.json()] == [vid]


def test_get_missing_vehicle_is_404(api_client):
    r = api_client.get("/api/vehicles/999")
    assert r.status_code == 404
