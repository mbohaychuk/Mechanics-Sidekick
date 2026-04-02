# app/services/job_service.py
from app.models.job import Job
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository


class JobService:
    def __init__(self, job_repo: JobRepository, vehicle_repo: VehicleRepository) -> None:
        self._job_repo = job_repo
        self._vehicle_repo = vehicle_repo

    def add_job(self, vehicle_id: int, title: str, description: str | None = None) -> Job:
        if self._vehicle_repo.get_by_id(vehicle_id) is None:
            raise ValueError(f"Vehicle {vehicle_id} not found")
        return self._job_repo.create(vehicle_id=vehicle_id, title=title, description=description)

    def get_job(self, job_id: int) -> Job:
        job = self._job_repo.get_by_id(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return job

    def list_jobs(self, vehicle_id: int) -> list[Job]:
        return self._job_repo.list_by_vehicle(vehicle_id)
