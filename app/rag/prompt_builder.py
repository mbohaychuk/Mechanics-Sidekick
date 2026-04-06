# app/rag/prompt_builder.py
"""Build system-prompt and message lists for Ollama /api/chat requests."""
from app.models.chat_message import ChatMessage
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.vehicle import Vehicle


def build_system_prompt(vehicle: Vehicle) -> str:
    return (
        "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance.\n\n"
        f"The vehicle you are assisting with is: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}.\n\n"
        "Rules:\n"
        "- Answer ONLY using the manual excerpts provided below.\n"
        "- Never invent torque specs, fluid types, measurements, or procedures.\n"
        "- Each excerpt includes a Section and Summary line. "
        "Use both together to judge whether the excerpt applies to this vehicle's engine. "
        f"You MUST use only excerpts that match the vehicle's engine ({vehicle.engine}). "
        "If an excerpt's Section or Summary indicates a different engine variant, ignore it entirely. "
        "If you discarded excerpts because they were for the wrong engine variant, say so at the end of your answer.\n"
        "- If the answer is not in the provided context, say: "
        "\"I could not find this in the available manuals.\"\n"
        "- Keep answers concise and mechanic-friendly.\n"
        "- Always cite your sources at the end of your answer.\n\n"
        "Answer format:\n"
        "Answer: <direct answer>\n\n"
        "Sources:\n"
        "- <filename>, page <number>"
    )


def build_messages(
    job: Job,
    vehicle: Vehicle,
    recent_messages: list[ChatMessage],
    chunks: list[tuple[DocumentChunk, float]],
    question: str,
    document_map: dict[int, str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt(vehicle)}]

    job_context = f"Current job: {job.title}"
    messages.append({"role": "system", "content": job_context})

    context_parts = []
    for i, (chunk, _score) in enumerate(chunks, start=1):
        page_label = f"page {chunk.page_number}" if chunk.page_number is not None else "page unknown"
        filename = document_map.get(chunk.document_id, f"document_{chunk.document_id}")
        section_line = f"Section: {chunk.section_title}\n" if chunk.section_title else ""
        summary_line = f"Summary: {chunk.context_summary}\n" if chunk.context_summary else ""
        context_parts.append(f"[{i}] {filename}, {page_label}:\n{section_line}{summary_line}{chunk.content}")
    messages.append({"role": "system", "content": "Manual excerpts:\n\n" + "\n\n".join(context_parts)})

    for msg in recent_messages:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": question})
    return messages
