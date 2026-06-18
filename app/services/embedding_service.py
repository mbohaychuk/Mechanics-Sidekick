from app.services.llm_backend import LLMBackend


class EmbeddingService:
    def __init__(self, backend: LLMBackend, model: str) -> None:
        self._backend = backend
        self._model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per text string."""
        return self._backend.embed(texts, self._model)

    def embed_query(self, query: str) -> list[float]:
        """Return a single embedding for a query string."""
        return self._backend.embed([query], self._model)[0]
