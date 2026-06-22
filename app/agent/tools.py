import json

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
                    "description": "What to look up, e.g. 'front brake caliper torque spec'. Fix typos "
                    "and spell out abbreviations, but copy any trouble code or part number exactly.",
                },
                "intent": {
                    "type": "string",
                    "enum": ["lookup", "procedure"],
                    "description": "'lookup' for a specific spec/value/code (capacity, torque, fluid "
                    "type, DTC code); 'procedure' for a how-to or repair sequence. Tunes the search.",
                },
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
    intent: str | None = None,
) -> dict:
    normalized = (intent or "").strip().lower()  # the model may emit 'Lookup'/'PROCEDURE'
    mode = normalized if normalized in ("lookup", "procedure") else "auto"
    ranked = retrieval.retrieve(vehicle_id=vehicle_id, question=query, mode=mode)
    sources: list[dict] = []
    excerpts: list[str] = []
    for i, (chunk, score) in enumerate(ranked, start=1):
        doc = doc_repo.get_by_id(chunk.document_id)
        filename = doc.file_name if doc else f"document_{chunk.document_id}"
        page = chunk.page_number
        sources.append({"filename": filename, "page": page, "score": round(score, 4)})
        page_label = f"page {page}" if page is not None else "page unknown"
        # Include the section/variant context (e.g. "ENGINE - 5.0L | …") so the model can tell which
        # engine/system an otherwise-generic spec belongs to and not mix variants.
        where = f"{filename}, {page_label}"
        section = getattr(chunk, "section_title", None)
        if section:
            where += f" — {section}"
        excerpts.append(f"[{i}] {where}:\n{chunk.content}")
    model_text = "\n\n".join(excerpts) if excerpts else "No relevant excerpts found in the manuals."
    return {"sources": sources, "model_text": model_text}


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for information not in the uploaded manuals — recalls, "
            "technical service bulletins, common failure patterns, part numbers, or general "
            "procedures. Use this only when search_manuals does not cover the question. Returns a "
            "short answer plus source snippets with their URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query.",
                }
            },
            "required": ["query"],
        },
    },
}


GET_DIAGNOSTICS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_diagnostic_reports",
        "description": (
            "Look up this vehicle's past diagnostic health-check reports (overall status and "
            "per-system findings with recommendations). Use this when the user asks about the "
            "vehicle's condition, history, or a prior diagnosis. Optionally filter by a keyword."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to focus on, e.g. 'fuel' or 'cooling'.",
                }
            },
        },
    },
}


def execute_get_diagnostic_reports(diag_repo, vehicle_id: int, query: str | None = None,
                                   limit: int = 3) -> dict:
    rows = diag_repo.list_by_vehicle(vehicle_id, limit=limit, status="completed")
    if not rows:
        return {"sources": [], "model_text": "No diagnostic health reports on file for this vehicle yet."}

    sources: list[dict] = []
    blocks: list[str] = []
    q = (query or "").strip().lower()
    for r in rows:
        date = r.ended_utc.date().isoformat() if r.ended_utc else r.started_utc.date().isoformat()
        sources.append({"kind": "diagnostic", "session_id": r.id, "date": date,
                        "overall_status": r.overall_status or "unknown"})
        try:
            report = json.loads(r.report_json) if r.report_json else {"findings": []}
        except (ValueError, TypeError):
            report = {"findings": []}  # one corrupt report row must not break the tool
        header = f"Health check {date} — overall {r.overall_status or 'unknown'}"
        if r.summary:
            header += f": {r.summary}"
        lines = [header]
        for f in report.get("findings", []):
            text = (f"  - {f.get('system')} [{f.get('severity')}]: {f.get('observation')}. "
                    f"{f.get('interpretation', '')} Recommendation: {f.get('recommendation', '')}")
            if not q or q in text.lower():
                lines.append(text)
        blocks.append("\n".join(lines))

    return {"sources": sources, "model_text": "\n\n".join(blocks)}


def execute_web_search(client, query: str, max_results: int = 5) -> dict:
    response = client.search(
        query=query,
        include_answer=True,
        search_depth="basic",
        max_results=max_results,
    )
    answer = response.get("answer")
    results = response.get("results", [])
    lines: list[str] = []
    if answer:
        lines.append(f"Answer: {answer}")
    for i, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        content = result.get("content", "")
        lines.append(f"[{i}] {title} ({url})\n{content}")
    model_text = "\n\n".join(lines) if lines else "No relevant web results found."
    return {"sources": [], "model_text": model_text}
