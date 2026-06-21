from unittest.mock import MagicMock

from typer.testing import CliRunner

from app import cli
from app.agent.orchestrator import AgentOrchestrator
from app.agent.provider import ProviderTurn
from app.models.job import Job
from app.models.vehicle import Vehicle
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository

runner = CliRunner()


class _FakeProvider:
    def stream_turn(self, messages, tools, max_tokens=None, response_format=None):
        yield {"type": "token", "text": "Torque is 129 Nm."}
        yield {"type": "turn", "turn": ProviderTurn(text="Torque is 129 Nm.", tool_calls=[])}


def _fake_orchestrator(session, settings, obd_host=None):
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    return AgentOrchestrator(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval=retrieval,
        provider=_FakeProvider(),
    )


def _temp_db_with_job(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.settings, "db_path", str(tmp_path / "cli.db"))
    monkeypatch.setattr(cli, "_engine", None)
    monkeypatch.setattr(cli, "_Session", None)
    cli._get_engine()
    s = cli._Session()
    v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L")
    s.add(v)
    s.flush()
    s.add(Job(vehicle_id=v.id, title="brakes"))
    s.commit()
    s.close()


def test_cli_chat_ask_streams_the_agent_answer(tmp_path, monkeypatch):
    # The CLI must drive the SAME AgentOrchestrator the web uses and stream its output.
    _temp_db_with_job(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.factories.make_chat_orchestrator", _fake_orchestrator)

    result = runner.invoke(cli.app, ["chat", "ask", "1", "what is the caliper torque?"])

    assert result.exit_code == 0
    assert "Torque is 129 Nm." in result.output


def test_cli_chat_ask_no_key_shows_actionable_message(tmp_path, monkeypatch):
    _temp_db_with_job(tmp_path, monkeypatch)

    def boom(session, settings, obd_host=None):
        raise RuntimeError("missing credentials")

    monkeypatch.setattr("app.services.factories.make_chat_orchestrator", boom)

    result = runner.invoke(cli.app, ["chat", "ask", "1", "q"])

    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in result.output


def test_cli_chat_ask_exits_nonzero_on_agent_error(tmp_path, monkeypatch):
    # An agent/provider error (emitted as an event, not an exception) must FAIL the command
    # so it's scriptable — not exit 0 with the error merely printed.
    _temp_db_with_job(tmp_path, monkeypatch)

    def erroring(session, settings, obd_host=None):
        orch = _fake_orchestrator(session, settings)
        orch.run = lambda *a, **k: iter([
            {"type": "error", "detail": "max_iterations_reached"}, {"type": "done"},
        ])
        return orch

    monkeypatch.setattr("app.services.factories.make_chat_orchestrator", erroring)
    result = runner.invoke(cli.app, ["chat", "ask", "1", "q"])
    assert result.exit_code == 1
