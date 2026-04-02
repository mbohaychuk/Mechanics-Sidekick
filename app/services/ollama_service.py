import ollama


class OllamaService:
    """Low-level wrapper around the Ollama Python client."""

    def __init__(self, base_url: str) -> None:
        self._client = ollama.Client(host=base_url)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Return one embedding vector per input text."""
        response = self._client.embed(model=model, input=texts)
        return response.embeddings

    def chat(self, messages: list[dict], model: str) -> str:
        """Send a chat request and return the assistant reply text."""
        response = self._client.chat(model=model, messages=messages)
        return response.message.content
