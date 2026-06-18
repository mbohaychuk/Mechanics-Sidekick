import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.ingestion import ingest_document
from app.api.schemas import DocumentOut
from app.config import settings
from app.repositories.document_repository import DocumentRepository
from app.repositories.vehicle_repository import VehicleRepository

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/vehicles/{vehicle_id}/documents", response_model=list[DocumentOut])
def list_documents(vehicle_id: int, session: Session = Depends(get_session)):
    return DocumentRepository(session).list_by_vehicle(vehicle_id)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: Session = Depends(get_session)):
    doc = DocumentRepository(session).get_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    return doc


@router.post("/vehicles/{vehicle_id}/documents", response_model=DocumentOut, status_code=202)
def upload_document(
    vehicle_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    if VehicleRepository(session).get_by_id(vehicle_id) is None:
        raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Only PDF uploads are accepted")

    file_name = Path(file.filename or "upload.pdf").name or "upload.pdf"
    suffix = Path(file_name).suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        written = 0
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Upload too large")
            tmp.write(chunk)
        tmp.flush()

        doc = DocumentRepository(session).create(
            vehicle_id=vehicle_id,
            file_name=file_name,
            stored_path="",
        )
        session.commit()  # persist so the background worker's new session sees the row

        background_tasks.add_task(
            ingest_document,
            request.app.state.session_factory,
            settings,
            doc.id,
            tmp.name,
        )
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return doc
