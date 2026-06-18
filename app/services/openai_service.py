from openai import OpenAI


class OpenAIService:
    """Low-level wrapper around the OpenAI client.

    Mirrors OllamaService's surface (embed, chat) so it is a drop-in backend
    for EmbeddingService and ContextualizationService.
    """

    def __init__(self, api_key: str, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=api_key)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        response = self._client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    def chat(self, messages: list[dict], model: str) -> str:
        response = self._client.chat.completions.create(model=model, messages=messages)
        return response.choices[0].message.content or ""
