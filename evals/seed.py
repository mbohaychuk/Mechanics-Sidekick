# evals/seed.py
"""Seed helpers for the eval runner.

ensure_vehicle() finds-or-creates a vehicle row matching the entry's
vehicle_context. ensure_pdf_ingested() ingests the named PDF for that
vehicle if no Document row already exists for it. Both are cached per run
to avoid duplicate work across entries that share a vehicle/document.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository

_vehicle_cache: dict[tuple, int] = {}
_document_cache: set[tuple[int, str]] = set()


def ensure_vehicle(session: Session, ctx: dict) -> int:
    key = (ctx["year"], ctx["make"], ctx["model"], ctx["engine"])
    if key in _vehicle_cache:
        return _vehicle_cache[key]

    existing = (
        session.query(Vehicle)
        .filter_by(year=ctx["year"], make=ctx["make"], model=ctx["model"], engine=ctx["engine"])
        .first()
    )
    if existing is not None:
        _vehicle_cache[key] = existing.id
        return existing.id

    vehicle = VehicleRepository(session).create(
        year=ctx["year"], make=ctx["make"], model=ctx["model"], engine=ctx["engine"],
    )
    session.flush()
    _vehicle_cache[key] = vehicle.id
    return vehicle.id


def ensure_pdf_ingested(
    session: Session,
    vehicle_id: int,
    pdf_filename: str,
    docs_dir: str,
    document_service,
) -> None:
    """Ingest the named PDF for the vehicle if not already present.

    pdf_filename is the bare basename. The harness searches for it under
    settings.docs_dir recursively.
    """
    cache_key = (vehicle_id, pdf_filename)
    if cache_key in _document_cache:
        return

    existing = (
        session.query(Document)
        .filter_by(vehicle_id=vehicle_id, file_name=pdf_filename, processing_status="ready")
        .first()
    )
    if existing is not None:
        _document_cache.add(cache_key)
        return

    candidates = list(Path(docs_dir).rglob(pdf_filename))
    if not candidates:
        raise FileNotFoundError(
            f"PDF not found: {pdf_filename} (searched under {docs_dir} recursively). "
            "Place the file there before running evals."
        )
    document_service.add_document(vehicle_id=vehicle_id, pdf_path=str(candidates[0]))
    session.flush()
    _document_cache.add(cache_key)


def reset_caches() -> None:
    """Clear the module caches; call at the start of each new runner invocation."""
    _vehicle_cache.clear()
    _document_cache.clear()
