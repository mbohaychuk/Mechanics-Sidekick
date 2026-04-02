# app/repositories/job_repository.py
from sqlalchemy.orm import Session
from app.models.job import Job


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, vehicle_id: int, title: str, description: str | None = None) -> Job:
        job = Job(vehicle_id=vehicle_id, title=title, description=description)
        self.session.add(job)
        return job

    def get_by_id(self, job_id: int) -> Job | None:
        return self.session.get(Job, job_id)

    def list_by_vehicle(self, vehicle_id: int) -> list[Job]:
        return (
            self.session.query(Job)
            .filter(Job.vehicle_id == vehicle_id)
            .order_by(Job.id)
            .all()
        )
