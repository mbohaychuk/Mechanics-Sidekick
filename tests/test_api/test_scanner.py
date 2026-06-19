def test_scanner_status_no_host(api_client):
    r = api_client.get("/api/scanner/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["scanner_reachable"] is False


def test_scanner_status_reachable(api_client):
    class FakeHost:
        available = True

        def call(self, name, args):
            return '{"vin": "WAUZZZ", "protocol": "ISO 15765-4"}'

        def stop(self):
            pass

    api_client.app.state.obd_host = FakeHost()
    body = api_client.get("/api/scanner/status").json()
    assert body["available"] is True
    assert body["scanner_reachable"] is True


def test_scanner_status_server_up_but_scanner_unreachable(api_client):
    class FakeHost:
        available = True

        def call(self, name, args):
            return "[tool error] [UNABLE_TO_CONNECT] adapter not reachable at socket://localhost:35000"

        def stop(self):
            pass

    api_client.app.state.obd_host = FakeHost()
    body = api_client.get("/api/scanner/status").json()
    assert body["available"] is True
    assert body["scanner_reachable"] is False
