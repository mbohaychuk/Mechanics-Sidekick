import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.job_repository import JobRepository
from app.services.vehicle_service import VehicleService
from app.services.job_service import JobService


@pytest.fixture
def vehicle(db_session):
    svc = VehicleService(VehicleRepository(db_session))
    v = svc.add_vehicle(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    return v


def test_add_job(db_session, vehicle):
    svc = JobService(JobRepository(db_session), VehicleRepository(db_session))
    job = svc.add_job(vehicle_id=vehicle.id, title="Front Brake Replacement")
    db_session.flush()
    assert job.id is not None
    assert job.title == "Front Brake Replacement"
    assert job.vehicle_id == vehicle.id
    assert job.status == "open"


def test_add_job_raises_when_vehicle_missing(db_session):
    svc = JobService(JobRepository(db_session), VehicleRepository(db_session))
    with pytest.raises(ValueError, match="Vehicle 999 not found"):
        svc.add_job(vehicle_id=999, title="Test Job")


def test_get_job_raises_when_not_found(db_session):
    svc = JobService(JobRepository(db_session), VehicleRepository(db_session))
    with pytest.raises(ValueError, match="Job 999 not found"):
        svc.get_job(999)


def test_list_jobs_by_vehicle(db_session, vehicle):
    svc = JobService(JobRepository(db_session), VehicleRepository(db_session))
    svc.add_job(vehicle.id, "Brake Replacement")
    svc.add_job(vehicle.id, "Oil Change")
    db_session.flush()
    assert len(svc.list_jobs(vehicle.id)) == 2
