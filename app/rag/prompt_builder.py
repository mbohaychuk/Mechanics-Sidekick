# app/rag/prompt_builder.py
"""Build system-prompt and message lists for Ollama /api/chat requests."""
from app.models.chat_message import ChatMessage
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.vehicle import Vehicle


def build_system_prompt() -> str:
    return (
        "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance.\n\n"
        "Rules:\n"
        "- Answer ONLY using the manual excerpts provided below.\n"
        "- Never invent torque specs, fluid types, measurements, or procedures.\n"
        "- If the answer is not in the provided context, say: "
        "\"I could not find this in the available manuals.\"\n"
        "- Keep answers concise and mechanic-friendly.\n"
        "- Always cite your sources at the end of your answer.\n\n"
        "Answer format:\n"
        "Answer: [direct answer]\n\n"
        "Sources:\n"
        "- [filename], page [page]"
    )


def build_messages(
    job: Job,
    vehicle: Vehicle,
    recent_messages: list[ChatMessage],
    chunks: list[tuple[DocumentChunk, float]],
    question: str,
    document_map: dict[int, str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt()}]

    job_context = (
        f"Current job: {job.title}\n"
        f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model} {vehicle.engine}"
    )
    messages.append({"role": "system", "content": job_context})

    context_parts = []
    for i, (chunk, _score) in enumerate(chunks, start=1):
        page_label = f"page {chunk.page_number}" if chunk.page_number is not None else "page unknown"
        filename = document_map.get(chunk.document_id, f"document_{chunk.document_id}")
        context_parts.append(f"[{i}] {filename}, {page_label}:\n{chunk.content}")
    messages.append({"role": "system", "content": "Manual excerpts:\n\n" + "\n\n".join(context_parts)})

    for msg in recent_messages:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": question})
    return messages
