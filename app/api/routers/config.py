from fastapi import APIRouter

from app.api.schemas import ConfigOut
from app.config import settings

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ConfigOut)
def get_config() -> ConfigOut:
    return ConfigOut(
        openai_key_present=bool(settings.openai_api_key),
        obd_mcp_enabled=settings.obd_mcp_enabled,
        obd_port=settings.obd_port,
        web_search_enabled=settings.web_search_enabled,
        web_search_key_present=bool(settings.tavily_api_key),
        chat_model=settings.openai_chat_model,
        embed_model=settings.openai_embed_model,
    )
