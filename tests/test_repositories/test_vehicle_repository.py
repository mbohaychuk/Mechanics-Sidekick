# tests/test_repositories/test_vehicle_repository.py
import pytest
from app.repositories.vehicle_repository import VehicleRepository


def test_create_vehicle(db_session):
    repo = VehicleRepository(db_session)
    vehicle = repo.create(year=2018, make="Ford", model="F-150", engine="5.0L V8")
    db_session.flush()
    assert vehicle.id is not None
    assert vehicle.make == "Ford"


def test_get_vehicle_by_id(db_session):
    repo = VehicleRepository(db_session)
    created = repo.create(year=2020, make="Toyota", model="Tacoma", engine="3.5L V6")
    db_session.flush()
    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.model == "Tacoma"


def test_get_vehicle_by_id_missing(db_session):
    repo = VehicleRepository(db_session)
    assert repo.get_by_id(9999) is None


def test_list_all_vehicles(db_session):
    repo = VehicleRepository(db_session)
    repo.create(year=2018, make="Ford", model="F-150", engine="5.0L")
    repo.create(year=2020, make="Toyota", model="Camry", engine="2.5L")
    db_session.flush()
    vehicles = repo.list_all()
    assert len(vehicles) == 2
