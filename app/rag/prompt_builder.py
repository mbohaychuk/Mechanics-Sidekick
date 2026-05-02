# app/rag/prompt_builder.py
"""Build the assistant message list for Ollama /api/chat in the agentic flow.

The relevance grader has already filtered out engine-variant mismatches and
off-topic chunks before these messages are built, so the system prompt no
longer needs to lecture the LLM about engine variant filtering. It can focus
on grounding and citation.
"""
from app.models.chat_message import ChatMessage
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.vehicle import Vehicle


def build_system_prompt(vehicle: Vehicle) -> str:
    return (
        "You are Mechanic Sidekick, an expert assistant for automotive repair and maintenance.\n\n"
        f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model}, engine: {vehicle.engine}.\n\n"
        "Rules:\n"
        "- Answer ONLY using the manual excerpts provided below.\n"
        "- Never invent torque specs, fluid types, measurements, or procedures.\n"
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
    chunks: list[DocumentChunk],
    question: str,
    document_map: dict[int, str],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt(vehicle)}]
    messages.append({"role": "system", "content": f"Current job: {job.title}"})

    context_parts = []
    for i, chunk in enumerate(chunks, start=1):
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
