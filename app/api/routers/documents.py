from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import DocumentOut
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
