from sqlalchemy.ext.asyncio import AsyncSession

from ..settings_store import get_setting
from .anthropic import AnthropicAdapter
from .base import ProviderAdapter
from .fireworks import FireworksAdapter
from .openai import OpenAIAdapter

PROVIDERS = ("fireworks", "openai", "anthropic")


async def build_adapter(
    db: AsyncSession, provider: str, model: str = "", subagent: bool = False
) -> ProviderAdapter:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    model_key = f"{provider}_subagent_model" if subagent else f"{provider}_model"
    resolved_model = model or await get_setting(db, model_key)
    api_key = await get_setting(db, f"{provider}_api_key")
    if not api_key:
        raise RuntimeError(
            f"No API key configured for provider '{provider}'. Set it in Settings."
        )
    if provider == "fireworks":
        return FireworksAdapter(api_key=api_key, model=resolved_model)
    if provider == "openai":
        return OpenAIAdapter(api_key=api_key, model=resolved_model)
    return AnthropicAdapter(api_key=api_key, model=resolved_model)
