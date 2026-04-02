# app/services/vehicle_service.py
from app.models.vehicle import Vehicle
from app.repositories.vehicle_repository import VehicleRepository


class VehicleService:
    def __init__(self, repo: VehicleRepository) -> None:
        self._repo = repo

    def add_vehicle(
        self,
        year: int,
        make: str,
        model: str,
        engine: str,
        vin: str | None = None,
        notes: str | None = None,
    ) -> Vehicle:
        return self._repo.create(year=year, make=make, model=model, engine=engine, vin=vin, notes=notes)

    def get_vehicle(self, vehicle_id: int) -> Vehicle:
        vehicle = self._repo.get_by_id(vehicle_id)
        if vehicle is None:
            raise ValueError(f"Vehicle {vehicle_id} not found")
        return vehicle

    def list_vehicles(self) -> list[Vehicle]:
        return self._repo.list_all()
