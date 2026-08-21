from sqlalchemy.ext.asyncio import AsyncSession

from ..settings_store import get_setting
from .base import ProviderAdapter
from .fireworks import FireworksAdapter

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
    # OpenAI (Responses API) and Anthropic adapters land in milestone 3.
    raise RuntimeError(f"Provider '{provider}' is not implemented yet.")
