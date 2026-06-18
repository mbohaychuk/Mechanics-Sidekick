import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.ingestion import ingest_document
from app.api.schemas import DocumentOut
from app.config import settings
from app.repositories.document_repository import DocumentRepository

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
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
    finally:
        tmp.close()

    doc = DocumentRepository(session).create(
        vehicle_id=vehicle_id,
        file_name=file.filename or "upload.pdf",
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
    return doc
