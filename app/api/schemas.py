import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


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


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    file_name: str
    document_type: str
    processing_status: str
    uploaded_utc: datetime
    chunks_total: int | None = None
    chunks_done: int | None = None


class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    role: str
    content: str
    sources_json: list[dict[str, Any]] | None
    created_utc: datetime

    @field_validator("sources_json", mode="before")
    @classmethod
    def _parse_sources(cls, v: Any) -> Any:
        if isinstance(v, str):
            return json.loads(v)
        return v


class ConfigOut(BaseModel):
    openai_key_present: bool
    obd_mcp_enabled: bool
    obd_port: str
    web_search_enabled: bool
    web_search_key_present: bool
    chat_model: str
    embed_model: str
