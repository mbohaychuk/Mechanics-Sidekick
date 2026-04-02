# tests/test_services/test_vehicle_service.py
import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_service import VehicleService


def test_add_vehicle_returns_vehicle(db_session):
    svc = VehicleService(VehicleRepository(db_session))
    vehicle = svc.add_vehicle(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    assert vehicle.id is not None
    assert vehicle.make == "Ford"


def test_get_vehicle_raises_when_not_found(db_session):
    svc = VehicleService(VehicleRepository(db_session))
    with pytest.raises(ValueError, match="Vehicle 999 not found"):
        svc.get_vehicle(999)


def test_list_vehicles_returns_all(db_session):
    svc = VehicleService(VehicleRepository(db_session))
    svc.add_vehicle(year=2018, make="Ford", model="F-150", engine="5.0L")
    svc.add_vehicle(year=2020, make="Toyota", model="Tacoma", engine="3.5L")
    db_session.flush()
    assert len(svc.list_vehicles()) == 2
