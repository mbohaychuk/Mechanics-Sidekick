from contextlib import contextmanager
from pathlib import Path

import typer

from app.config import settings
from app.db import Base, get_engine, get_session_factory
from app.utils.console import console, print_error, print_success, print_vehicle, print_job, print_answer

app = typer.Typer(name="mechanic-sidekick", help="Local RAG assistant for mechanics.")
vehicle_app = typer.Typer(help="Manage vehicles.")
document_app = typer.Typer(help="Manage documents.")
job_app = typer.Typer(help="Manage jobs.")
chat_app = typer.Typer(help="Chat within a job.")

app.add_typer(vehicle_app, name="vehicle")
app.add_typer(document_app, name="document")
app.add_typer(job_app, name="job")
app.add_typer(chat_app, name="chat")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        import app.models  # noqa: F401 — register all models with Base

        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = get_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(_engine)
    return _engine


@contextmanager
def get_session():
    engine = _get_engine()
    Session = get_session_factory(engine)
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _make_vehicle_service(session):
    from app.repositories.vehicle_repository import VehicleRepository
    from app.services.vehicle_service import VehicleService
    return VehicleService(VehicleRepository(session))


# ── Vehicle commands ──────────────────────────────────────────────────────────

@vehicle_app.command("add")
def vehicle_add():
    """Add a new vehicle."""
    year = typer.prompt("Year", type=int)
    make = typer.prompt("Make")
    model = typer.prompt("Model")
    engine = typer.prompt("Engine")
    vin = typer.prompt("VIN (optional, Enter to skip)", default="") or None
    notes = typer.prompt("Notes (optional, Enter to skip)", default="") or None

    with get_session() as session:
        svc = _make_vehicle_service(session)
        vehicle = svc.add_vehicle(year=year, make=make, model=model, engine=engine, vin=vin, notes=notes)
        session.flush()
        print_success(f"Vehicle added with ID {vehicle.id}")
        print_vehicle(vehicle)


@vehicle_app.command("list")
def vehicle_list():
    """List all vehicles."""
    with get_session() as session:
        svc = _make_vehicle_service(session)
        vehicles = svc.list_vehicles()
        if not vehicles:
            console.print("[dim]No vehicles found.[/dim]")
            return
        for v in vehicles:
            console.print(f"  [{v.id}] {v.year} {v.make} {v.model} — {v.engine}")


@vehicle_app.command("show")
def vehicle_show(vehicle_id: int):
    """Show details for a vehicle."""
    with get_session() as session:
        svc = _make_vehicle_service(session)
        try:
            vehicle = svc.get_vehicle(vehicle_id)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)
        print_vehicle(vehicle)
