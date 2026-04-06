# app/services/contextualization_service.py
from app.services.ollama_service import OllamaService


class ContextualizationService:
    """Generates a concise context sentence for each chunk before embedding.

    The context situates the chunk within its document — identifying the engine
    variant, system, and topic — so the embedding captures not just what the
    chunk says but where it lives in the manual. This is the core of contextual
    retrieval: retrieve precisely, even across multi-variant document sets.
    """

    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def generate_context(
        self,
        chunk_content: str,
        filename: str,
        page_number: int | None,
        chunk_index: int,
        total_chunks: int,
        section_title: str | None = None,
    ) -> str:
        page_label = str(page_number) if page_number is not None else "unknown"
        section_line = f"Section heading: {section_title}\n" if section_title else ""
        prompt = (
            "You are indexing a vehicle service manual for a semantic search system.\n\n"
            f"Document filename: {filename}\n"
            f"Page: {page_label}\n"
            f"{section_line}"
            f"Position: chunk {chunk_index + 1} of {total_chunks}\n\n"
            "Chunk content:\n"
            f"{chunk_content[:800]}\n\n"
            "Write one or two sentences (under 40 words total) that:\n"
            "- Identify which engine variant, transmission type, or vehicle system this content applies to "
            "(look in the filename, section heading, and content for clues like '4.2L', '6.0L', 'W12', 'AWD', system names)\n"
            "- Describe the specific topic, procedure, or specification this chunk covers\n\n"
            "Respond with only the sentences. No labels, no preamble."
        )
        messages = [{"role": "user", "content": prompt}]
        return self._ollama.chat(messages, self._model)
