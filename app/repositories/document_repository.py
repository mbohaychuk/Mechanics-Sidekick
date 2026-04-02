# app/repositories/document_repository.py
from sqlalchemy.orm import Session
from app.models.document import Document


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        vehicle_id: int,
        file_name: str,
        stored_path: str,
        document_type: str = "service_manual",
    ) -> Document:
        doc = Document(
            vehicle_id=vehicle_id,
            file_name=file_name,
            stored_path=stored_path,
            document_type=document_type,
        )
        self.session.add(doc)
        return doc

    def get_by_id(self, doc_id: int) -> Document | None:
        return self.session.get(Document, doc_id)

    def list_by_vehicle(self, vehicle_id: int) -> list[Document]:
        return (
            self.session.query(Document)
            .filter(Document.vehicle_id == vehicle_id)
            .order_by(Document.id)
            .all()
        )

    def update_status(self, doc_id: int, status: str) -> None:
        doc = self.session.get(Document, doc_id)
        if doc:
            doc.processing_status = status
