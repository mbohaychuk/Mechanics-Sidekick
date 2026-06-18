from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import VehicleCreate, VehicleOut
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_service import VehicleService

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def _service(session: Session) -> VehicleService:
    return VehicleService(VehicleRepository(session))


@router.get("", response_model=list[VehicleOut])
def list_vehicles(session: Session = Depends(get_session)):
    return _service(session).list_vehicles()


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, session: Session = Depends(get_session)):
    vehicle = _service(session).add_vehicle(**payload.model_dump())
    session.flush()
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, session: Session = Depends(get_session)):
    try:
        return _service(session).get_vehicle(vehicle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
