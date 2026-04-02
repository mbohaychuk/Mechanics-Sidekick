from app.services.ollama_service import OllamaService


class EmbeddingService:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per text string."""
        return self._ollama.embed(texts, self._model)

    def embed_query(self, query: str) -> list[float]:
        """Return a single embedding for a query string."""
        return self._ollama.embed([query], self._model)[0]
