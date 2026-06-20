import json

from app.agent.tools import execute_get_diagnostic_reports
from app.models.vehicle import Vehicle
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository


def _seed_completed(db_session, vehicle_id, overall, summary, findings):
    repo = DiagnosticSessionRepository(db_session)
    row = repo.create(vehicle_id=vehicle_id, live_session_id=None, protocol_name="default")
    db_session.commit()
    repo.complete(row.id, overall_status=overall, summary=summary,
                  report_json=json.dumps({"overall_status": overall, "summary": summary,
                                          "findings": findings}),
                  commentary_json="[]")
    db_session.commit()
    return row.id


def test_digest_includes_findings_and_citation_source(db_session):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="X"))
    db_session.commit()
    sid = _seed_completed(db_session, 1, "fair", "One lean bank.", [
        {"system": "fuel", "severity": "warn", "observation": "LTFT +14%",
         "interpretation": "Lean.", "recommendation": "Check vacuum leak.", "evidence": {}},
    ])
    out = execute_get_diagnostic_reports(DiagnosticSessionRepository(db_session), vehicle_id=1)
    assert "fuel" in out["model_text"]
    assert "Check vacuum leak." in out["model_text"]
    assert out["sources"][0] == {"kind": "diagnostic", "session_id": sid,
                                 "date": out["sources"][0]["date"], "overall_status": "fair"}


def test_no_reports_returns_friendly_text(db_session):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="X"))
    db_session.commit()
    out = execute_get_diagnostic_reports(DiagnosticSessionRepository(db_session), vehicle_id=1)
    assert out["sources"] == []
    assert "no diagnostic" in out["model_text"].lower()


def test_orchestrator_dispatches_diagnostic_tool(db_session):
    """A fake provider that calls get_diagnostic_reports then answers proves dispatch + advertising."""
    from app.agent.orchestrator import AgentOrchestrator
    from app.agent.provider import ProviderTurn, ToolCall
    from app.models.job import Job
    from app.repositories.chat_repository import ChatRepository
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.job_repository import JobRepository
    from app.repositories.vehicle_repository import VehicleRepository

    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="X"))
    db_session.commit()
    db_session.add(Job(vehicle_id=1, title="t", status="open"))
    db_session.commit()
    _seed_completed(db_session, 1, "good", "All clear.", [])

    advertised = {}

    class FakeProvider:
        def __init__(self):
            self._turn = 0
        def stream_turn(self, messages, tools, max_tokens=None):
            advertised["names"] = [t["function"]["name"] for t in tools]
            self._turn += 1
            if self._turn == 1:
                yield {"type": "turn", "turn": ProviderTurn(text="", tool_calls=[
                    ToolCall(id="c1", name="get_diagnostic_reports", arguments={})])}
            else:
                yield {"type": "token", "text": "Last check was all clear."}
                yield {"type": "turn", "turn": ProviderTurn(text="Last check was all clear.", tool_calls=[])}

    orch = AgentOrchestrator(
        chat_repo=ChatRepository(db_session), job_repo=JobRepository(db_session),
        vehicle_repo=VehicleRepository(db_session), doc_repo=DocumentRepository(db_session),
        retrieval=None, provider=FakeProvider(),
        diag_repo=DiagnosticSessionRepository(db_session),
    )
    events = list(orch.run(1, "any past health checks?"))
    assert "get_diagnostic_reports" in advertised["names"]
    assert any(e["type"] == "tool_call" and e["name"] == "get_diagnostic_reports" for e in events)
    assert any(e["type"] == "done" for e in events)
