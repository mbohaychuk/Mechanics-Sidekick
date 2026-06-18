from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import JobCreate, JobOut
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.job_service import JobService

router = APIRouter(prefix="/api", tags=["jobs"])


def _service(session: Session) -> JobService:
    return JobService(JobRepository(session), VehicleRepository(session))


@router.get("/vehicles/{vehicle_id}/jobs", response_model=list[JobOut])
def list_jobs(vehicle_id: int, session: Session = Depends(get_session)):
    return _service(session).list_jobs(vehicle_id)


@router.post("/vehicles/{vehicle_id}/jobs", response_model=JobOut, status_code=201)
def create_job(vehicle_id: int, payload: JobCreate, session: Session = Depends(get_session)):
    try:
        job = _service(session).add_job(vehicle_id=vehicle_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    session.flush()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)):
    try:
        return _service(session).get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
