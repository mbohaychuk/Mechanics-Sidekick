from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import RetrievalService

SEARCH_MANUALS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_manuals",
        "description": (
            "Search the uploaded service manuals for this vehicle. Use this to ground every "
            "factual answer (specifications, torque values, fluid types, procedures) in the "
            "manuals before answering. Returns the most relevant excerpts with their source "
            "filename and page number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, e.g. 'front brake caliper torque spec'.",
                }
            },
            "required": ["query"],
        },
    },
}


def execute_search_manuals(
    retrieval: RetrievalService,
    doc_repo: DocumentRepository,
    vehicle_id: int,
    query: str,
) -> dict:
    ranked = retrieval.retrieve(vehicle_id=vehicle_id, question=query)
    sources: list[dict] = []
    excerpts: list[str] = []
    for i, (chunk, score) in enumerate(ranked, start=1):
        doc = doc_repo.get_by_id(chunk.document_id)
        filename = doc.file_name if doc else f"document_{chunk.document_id}"
        page = chunk.page_number
        sources.append({"filename": filename, "page": page, "score": round(score, 4)})
        page_label = f"page {page}" if page is not None else "page unknown"
        excerpts.append(f"[{i}] {filename}, {page_label}:\n{chunk.content}")
    model_text = "\n\n".join(excerpts) if excerpts else "No relevant excerpts found in the manuals."
    return {"sources": sources, "model_text": model_text}
