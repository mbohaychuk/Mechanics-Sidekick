# app/repositories/vehicle_repository.py
from sqlalchemy.orm import Session
from app.models.vehicle import Vehicle


class VehicleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        year: int,
        make: str,
        model: str,
        engine: str,
        vin: str | None = None,
        notes: str | None = None,
    ) -> Vehicle:
        vehicle = Vehicle(year=year, make=make, model=model, engine=engine, vin=vin, notes=notes)
        self.session.add(vehicle)
        return vehicle

    def get_by_id(self, vehicle_id: int) -> Vehicle | None:
        return self.session.get(Vehicle, vehicle_id)

    def list_all(self) -> list[Vehicle]:
        return self.session.query(Vehicle).order_by(Vehicle.id).all()
