# evals/seed.py
"""Vehicle lookup for the eval runner.

The eval runner assumes the vehicle and its manuals are already ingested
(via `mechanic-sidekick vehicle add` and `document add`). find_vehicle()
resolves an entry's vehicle_context to a vehicle id and raises a clear
error if the vehicle is missing — the runner does not auto-create.
"""
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle

_vehicle_cache: dict[tuple, int] = {}


def find_vehicle(session: Session, ctx: dict) -> int:
    """Look up a vehicle by exact (year, make, model, engine) match."""
    key = (ctx["year"], ctx["make"], ctx["model"], ctx["engine"])
    if key in _vehicle_cache:
        return _vehicle_cache[key]

    vehicle = (
        session.query(Vehicle)
        .filter_by(year=ctx["year"], make=ctx["make"], model=ctx["model"], engine=ctx["engine"])
        .first()
    )
    if vehicle is None:
        raise LookupError(
            f"No vehicle in DB matches {ctx['year']} {ctx['make']} {ctx['model']} ({ctx['engine']!r}). "
            "Add it with `mechanic-sidekick vehicle add`, then ingest its manuals with "
            "`mechanic-sidekick document add <vehicle_id> <path> --recursive` before running evals."
        )

    _vehicle_cache[key] = vehicle.id
    return vehicle.id


def reset_caches() -> None:
    """Clear the module cache; call at the start of each new runner invocation."""
    _vehicle_cache.clear()
