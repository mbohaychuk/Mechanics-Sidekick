from app.config import Settings
from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService
from app.services.ollama_service import OllamaService
from app.services.openai_service import OpenAIService


def make_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.embed_provider == "openai":
        return EmbeddingService(
            OpenAIService(api_key=settings.openai_api_key or None),
            settings.openai_embed_model,
        )
    return EmbeddingService(
        OllamaService(settings.ollama_base_url),
        settings.embed_model,
    )


def make_contextualization_service(settings: Settings) -> ContextualizationService:
    if settings.llm_provider == "openai":
        return ContextualizationService(
            OpenAIService(api_key=settings.openai_api_key or None),
            settings.openai_chat_model,
        )
    return ContextualizationService(
        OllamaService(settings.ollama_base_url),
        settings.context_model,
    )
