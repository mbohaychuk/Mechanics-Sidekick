# app/rag/prompt_builder.py


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
    job,
    vehicle,
    recent_messages: list,
    chunks: list[tuple],
    question: str,
    document_map: dict[int, str],
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": build_system_prompt()}]

    job_context = (
        f"Current job: {job.title}\n"
        f"Vehicle: {vehicle.year} {vehicle.make} {vehicle.model} {vehicle.engine}"
    )
    messages.append({"role": "system", "content": job_context})

    context_parts = [
        f"[{i}] {document_map.get(chunk.document_id, f'document_{chunk.document_id}')}, "
        f"page {chunk.page_number}:\n{chunk.content}"
        for i, (chunk, _score) in enumerate(chunks, start=1)
    ]
    messages.append({"role": "system", "content": "Manual excerpts:\n\n" + "\n\n".join(context_parts)})

    for msg in recent_messages:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": question})
    return messages
