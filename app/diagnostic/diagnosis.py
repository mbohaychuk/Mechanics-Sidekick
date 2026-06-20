from __future__ import annotations

from app.agent.tools import execute_search_manuals, execute_web_search
from app.diagnostic.anomaly import AnomalyFlag
from app.diagnostic.report import Finding


class Diagnoser:
    def __init__(self, retrieval, doc_repo, web_client, vehicle_id: int, settings) -> None:
        self._retrieval = retrieval
        self._doc_repo = doc_repo
        self._web_client = web_client
        self._vehicle_id = vehicle_id
        self._settings = settings

    def diagnose(self, flag: AnomalyFlag, vehicle_label: str) -> Finding:
        query = f"{flag.system} {flag.detail} {vehicle_label}"
        manual = execute_search_manuals(self._retrieval, self._doc_repo, self._vehicle_id, query)
        sources = list(manual["sources"])
        top_score = max((s["score"] for s in sources), default=0.0)

        web_text = ""
        if top_score < self._settings.diag_manual_min_score and self._web_client is not None:
            web = execute_web_search(self._web_client, query)
            web_text = web["model_text"]

        return Finding(
            system=flag.system,
            severity=flag.severity,
            observation=flag.detail,
            evidence={
                "readings": [{"pid": flag.pid, "value": flag.value}],
                "sources": sources,
                "manual_text": manual["model_text"],
                "web_text": web_text,
            },
        )
