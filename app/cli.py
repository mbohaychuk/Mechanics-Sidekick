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
_Session = None


def _get_engine():
    global _engine, _Session
    if _engine is None:
        import app.models  # noqa: F401 — register all models with Base

        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = get_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(_engine)
        _Session = get_session_factory(_engine)
    return _engine


@contextmanager
def get_session():
    _get_engine()  # ensure engine + session factory are initialized
    session = _Session()
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
        session.flush()  # populate vehicle.id before printing (create doesn't flush automatically)
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


def _make_job_service(session):
    from app.repositories.vehicle_repository import VehicleRepository
    from app.repositories.job_repository import JobRepository
    from app.services.job_service import JobService
    return JobService(JobRepository(session), VehicleRepository(session))


# ── Job commands ──────────────────────────────────────────────────────────────

@job_app.command("add")
def job_add(vehicle_id: int):
    """Add a new job for a vehicle."""
    title = typer.prompt("Job title")
    description = typer.prompt("Description (optional, Enter to skip)", default="") or None

    with get_session() as session:
        svc = _make_job_service(session)
        try:
            job = svc.add_job(vehicle_id=vehicle_id, title=title, description=description)
            session.flush()  # populate job.id before printing
            print_success(f"Job created with ID {job.id}")
            print_job(job)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)


@job_app.command("list")
def job_list(vehicle_id: int):
    """List all jobs for a vehicle."""
    with get_session() as session:
        svc = _make_job_service(session)
        jobs = svc.list_jobs(vehicle_id)
        if not jobs:
            console.print("[dim]No jobs found for this vehicle.[/dim]")
            return
        for j in jobs:
            console.print(f"  [{j.id}] {j.title} — {j.status}")


@job_app.command("show")
def job_show(job_id: int):
    """Show details for a job."""
    with get_session() as session:
        svc = _make_job_service(session)
        try:
            job = svc.get_job(job_id)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)
        print_job(job)


def _make_document_service(session):
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.chunk_repository import ChunkRepository
    from app.services.document_service import DocumentService
    from app.services.pdf_service import PDFService
    from app.services.chunking_service import ChunkingService
    from app.services.embedding_service import EmbeddingService
    from app.services.ollama_service import OllamaService

    ollama_svc = OllamaService(settings.ollama_base_url)
    embedding_svc = EmbeddingService(ollama_svc, settings.embed_model)
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=ChunkingService(settings.chunk_size, settings.chunk_overlap),
        embedding_service=embedding_svc,
        docs_dir=settings.docs_dir,
    )


# ── Document commands ─────────────────────────────────────────────────────────

@document_app.command("add")
def document_add(
    vehicle_id: int,
    pdf_path: str,
    doc_type: str = typer.Option("service_manual", "--type", help="Document type label"),
):
    """Upload and process a PDF manual for a vehicle."""
    with get_session() as session:
        svc = _make_document_service(session)
        try:
            with console.status(f"Processing {pdf_path}...", spinner="dots"):
                doc = svc.add_document(vehicle_id=vehicle_id, pdf_path=pdf_path, document_type=doc_type)
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            print_error(str(e))
            raise typer.Exit(1)
        print_success(f"Document '{doc.file_name}' processed and ready (ID: {doc.id})")


@document_app.command("list")
def document_list(vehicle_id: int):
    """List all documents for a vehicle."""
    with get_session() as session:
        svc = _make_document_service(session)
        docs = svc.list_documents(vehicle_id)
        if not docs:
            console.print("[dim]No documents found for this vehicle.[/dim]")
            return
        for d in docs:
            console.print(f"  [{d.id}] {d.file_name} — {d.document_type} — {d.processing_status}")


def _make_chat_service(session):
    from app.repositories.vehicle_repository import VehicleRepository
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.job_repository import JobRepository
    from app.repositories.chat_repository import ChatRepository
    from app.repositories.chunk_repository import ChunkRepository
    from app.services.ollama_service import OllamaService
    from app.services.embedding_service import EmbeddingService
    from app.services.retrieval_service import RetrievalService
    from app.services.chat_service import ChatService

    ollama_svc = OllamaService(settings.ollama_base_url)
    embedding_svc = EmbeddingService(ollama_svc, settings.embed_model)
    retrieval_svc = RetrievalService(ChunkRepository(session), embedding_svc, settings.top_k_chunks)

    return ChatService(
        chat_repo=ChatRepository(session),
        job_repo=JobRepository(session),
        vehicle_repo=VehicleRepository(session),
        doc_repo=DocumentRepository(session),
        retrieval_service=retrieval_svc,
        ollama_service=ollama_svc,
        chat_model=settings.chat_model,
        recent_messages_limit=settings.recent_messages,
    )


# ── Chat commands ─────────────────────────────────────────────────────────────

@chat_app.command("ask")
def chat_ask(job_id: int, question: str):
    """Ask a single question in a job context."""
    with get_session() as session:
        svc = _make_chat_service(session)
        try:
            with console.status("Thinking...", spinner="dots"):
                answer, sources = svc.ask(job_id=job_id, question=question)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error: {e}")
            raise typer.Exit(1)
        print_answer(answer, sources)


@chat_app.command("start")
def chat_start(job_id: int):
    """Start an interactive chat session for a job."""
    # Validate job exists and capture header info before entering the loop
    with get_session() as session:
        job_svc = _make_job_service(session)
        try:
            job = job_svc.get_job(job_id)
            header = f"{job.title} (ID: {job.id})"
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)

    console.print(f"\n[bold cyan]Job:[/bold cyan] {header}")
    console.print("[dim]Type your question, or 'quit' to exit.[/dim]\n")

    while True:
        try:
            question = typer.prompt("You")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if question.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Session ended.[/dim]")
            break

        if not question.strip():
            continue

        with get_session() as session:
            svc = _make_chat_service(session)
            try:
                with console.status("Thinking...", spinner="dots"):
                    answer, sources = svc.ask(job_id=job_id, question=question)
            except Exception as e:
                print_error(f"Error: {e}")
                continue
            print_answer(answer, sources)
