# app/utils/paths.py
from pathlib import Path


def get_document_path(
    docs_dir: str,
    vehicle_id: int,
    document_id: int,
    filename: str,
) -> Path:
    safe_name = filename.replace(" ", "_")
    return Path(docs_dir) / str(vehicle_id) / f"{document_id}_{safe_name}"
