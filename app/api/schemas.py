from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    year: int
    make: str
    model: str
    engine: str
    vin: str | None = None
    notes: str | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    year: int
    make: str
    model: str
    engine: str
    vin: str | None
    notes: str | None
    created_utc: datetime


class JobCreate(BaseModel):
    title: str
    description: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    title: str
    description: str | None
    status: str
    created_utc: datetime
