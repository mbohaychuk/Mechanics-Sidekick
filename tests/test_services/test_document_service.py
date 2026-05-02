# tests/test_services/test_document_service.py
import pytest
from unittest.mock import MagicMock

from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.services.contextualization_service import ContextualizationService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.metadata_extractor import MetadataExtractor
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.table_chunker import TableChunker


@pytest.fixture
def vehicle(db_session):
    v = VehicleRepository(db_session).create(year=2006, make="Audi", model="A8", engine="4.2L V8")
    db_session.flush()
    return v


def _make_pdf(tmp_path):
    p = tmp_path / "manual.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake\n")  # contents irrelevant — PDFService is mocked
    return str(p)


def _make_service(db_session, tmp_path, **overrides):
    pdf_service = overrides.get("pdf_service") or MagicMock(spec=PDFService)
    chunking_service = overrides.get("chunking_service") or MagicMock(spec=StructuredChunkingService)
    table_chunker = overrides.get("table_chunker") or MagicMock(spec=TableChunker)
    contextualization_service = overrides.get("contextualization_service") or MagicMock(spec=ContextualizationService)
    embedding_service = overrides.get("embedding_service") or MagicMock(spec=EmbeddingService)
    metadata_extractor = overrides.get("metadata_extractor") or MagicMock(spec=MetadataExtractor)

    return DocumentService(
        doc_repo=DocumentRepository(db_session),
        chunk_repo=ChunkRepository(db_session),
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        table_chunker=table_chunker,
        contextualization_service=contextualization_service,
        embedding_service=embedding_service,
        metadata_extractor=metadata_extractor,
        docs_dir=str(tmp_path / "docs"),
    )


def test_add_document_runs_table_then_prose_then_metadata_then_embed(db_session, vehicle, tmp_path):
    pdf_path = _make_pdf(tmp_path)

    pdf_service = MagicMock(spec=PDFService)
    pdf_service.extract_blocks.return_value = [{"page_number": 1, "blocks": []}]
    pdf_service.extract_tables.return_value = [{
        "page_number": 1,
        "tables": [{"bbox": (0, 0, 100, 100), "header": ["Bolt", "Nm"], "rows": [["Bolt", "Nm"], ["Head", "129"]]}],
    }]

    table_chunker = MagicMock(spec=TableChunker)
    table_chunker.chunk_tables.return_value = [
        {"chunk_index": 0, "page_number": 1, "section_title": "TORQUE",
         "content": "| Bolt | Nm |\n| --- | --- |\n| Head | 129 |",
         "chunk_kind": "table_whole", "table_id": "t_abc", "table_type": None},
        {"chunk_index": 1, "page_number": 1, "section_title": "TORQUE",
         "content": "[Section: TORQUE] [Table t_abc] Bolt: Head | Nm: 129",
         "chunk_kind": "table_row", "table_id": "t_abc", "table_type": None},
    ]
    table_chunker.bboxes_by_page.return_value = {1: [(0, 0, 100, 100)]}

    chunking_service = MagicMock(spec=StructuredChunkingService)
    chunking_service.chunk_blocks.return_value = [
        {"chunk_index": 2, "page_number": 1, "section_title": None, "content": "prose body"},
    ]

    metadata = MagicMock(spec=MetadataExtractor)
    metadata.extract_engine_variant.return_value = "4.2L"
    metadata.classify_table_type.return_value = "torque"

    contextualization = MagicMock(spec=ContextualizationService)
    contextualization.generate_context.side_effect = lambda **_: "ctx"

    embedding = MagicMock(spec=EmbeddingService)
    embedding.embed_texts.return_value = [[0.1] * 4, [0.2] * 4, [0.3] * 4]

    svc = _make_service(
        db_session, tmp_path,
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        table_chunker=table_chunker,
        contextualization_service=contextualization,
        embedding_service=embedding,
        metadata_extractor=metadata,
    )

    doc = svc.add_document(vehicle_id=vehicle.id, pdf_path=pdf_path)
    db_session.flush()

    # Prose chunker received the table bboxes for exclusion.
    call_kwargs = chunking_service.chunk_blocks.call_args.kwargs
    assert call_kwargs.get("exclude_bboxes_per_page") == {1: [(0, 0, 100, 100)]}

    # All three chunk kinds persisted.
    rows = ChunkRepository(db_session).list_by_vehicle(vehicle.id)
    kinds = sorted(r.chunk_kind for r in rows)
    assert kinds == ["prose", "table_row", "table_whole"]

    # Engine variant + table_type populated.
    table_rows = [r for r in rows if r.chunk_kind in ("table_row", "table_whole")]
    assert all(r.engine_variant == "4.2L" for r in table_rows)
    assert all(r.table_type == "torque" for r in table_rows)
    prose = [r for r in rows if r.chunk_kind == "prose"]
    assert all(r.engine_variant == "4.2L" for r in prose)
    assert all(r.table_type is None for r in prose)


def test_add_document_marks_failed_on_exception(db_session, vehicle, tmp_path):
    pdf_path = _make_pdf(tmp_path)

    pdf_service = MagicMock(spec=PDFService)
    pdf_service.extract_blocks.side_effect = RuntimeError("boom")

    svc = _make_service(db_session, tmp_path, pdf_service=pdf_service)

    with pytest.raises(RuntimeError, match="Document processing failed"):
        svc.add_document(vehicle_id=vehicle.id, pdf_path=pdf_path)

    docs = DocumentRepository(db_session).list_by_vehicle(vehicle.id)
    assert len(docs) == 1
    assert docs[0].processing_status == "failed"


def test_add_document_raises_when_pdf_missing(db_session, vehicle, tmp_path):
    svc = _make_service(db_session, tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.add_document(vehicle_id=vehicle.id, pdf_path="/no/such/file.pdf")
