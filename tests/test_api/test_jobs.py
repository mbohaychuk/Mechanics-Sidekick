def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def test_create_list_and_get_job(api_client):
    vid = _make_vehicle(api_client)

    created = api_client.post(
        f"/api/vehicles/{vid}/jobs",
        json={"title": "Oil leak", "description": "front main seal"},
    )
    assert created.status_code == 201
    job = created.json()
    assert job["title"] == "Oil leak"
    assert job["status"] == "open"
    assert job["vehicle_id"] == vid

    listed = api_client.get(f"/api/vehicles/{vid}/jobs")
    assert [j["id"] for j in listed.json()] == [job["id"]]

    got = api_client.get(f"/api/jobs/{job['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "Oil leak"


def test_create_job_for_missing_vehicle_is_404(api_client):
    r = api_client.post("/api/vehicles/999/jobs", json={"title": "x"})
    assert r.status_code == 404


def test_get_missing_job_is_404(api_client):
    assert api_client.get("/api/jobs/999").status_code == 404
