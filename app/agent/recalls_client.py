import httpx

_NHTSA_BASE = "https://api.nhtsa.gov"


class NhtsaRecallsClient:
    """Thin client over NHTSA's public, key-free recalls API.

    `recallsByVehicle` matches on the catalog spelling of a model (e.g. 'F-150', not 'F150');
    a model name that doesn't match returns an empty result rather than an error.
    """

    def __init__(self, base_url: str = _NHTSA_BASE, timeout_s: float = 15.0, http_client=None) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._http = http_client  # injected in tests; a fresh per-call client is used otherwise

    def recalls_by_vehicle(self, year: int, make: str, model: str) -> list[dict]:
        if self._http is not None:
            return self._fetch(self._http, year, make, model)
        with httpx.Client(timeout=self._timeout) as client:
            return self._fetch(client, year, make, model)

    def _fetch(self, client, year: int, make: str, model: str) -> list[dict]:
        resp = client.get(
            f"{self._base}/recalls/recallsByVehicle",
            params={"make": make, "model": model, "modelYear": year},
        )
        resp.raise_for_status()
        return resp.json().get("results") or []
