"""Runtime app settings stored in the DB (provider API keys, model defaults).

Secret values are encrypted at rest with a Fernet key derived from SA_SECRET_KEY.
"""

import base64
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import AppSetting

SECRET_KEYS = {
    "fireworks_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "exa_api_key",
}

PLAIN_KEYS = {
    "fireworks_model",
    "fireworks_subagent_model",
    "openai_model",
    "openai_subagent_model",
    "anthropic_model",
    "anthropic_subagent_model",
    "default_provider",
}

ALL_KEYS = SECRET_KEYS | PLAIN_KEYS

DEFAULTS = {
    "fireworks_model": "accounts/fireworks/models/deepseek-v4-pro",
    "fireworks_subagent_model": "accounts/fireworks/models/deepseek-v4-flash-0731",
    "openai_model": "gpt-5",
    "openai_subagent_model": "gpt-5-mini",
    "anthropic_model": "claude-sonnet-4-5",
    "anthropic_subagent_model": "claude-haiku-4-5",
    "default_provider": "fireworks",
}


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


async def get_setting(db: AsyncSession, key: str) -> str:
    row = await db.get(AppSetting, key)
    if row is None or not row.value:
        return DEFAULTS.get(key, "")
    if row.encrypted:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    if key not in ALL_KEYS:
        raise ValueError(f"Unknown setting: {key}")
    encrypted = key in SECRET_KEYS
    stored = _fernet().encrypt(value.encode()).decode() if encrypted and value else value
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=stored, encrypted=encrypted)
        db.add(row)
    else:
        row.value = stored
        row.encrypted = encrypted
    await db.commit()


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    """Return all settings; secret values are masked."""
    result: dict[str, str] = dict(DEFAULTS)
    rows = (await db.execute(select(AppSetting))).scalars().all()
    stored = {r.key: r for r in rows}
    for key in ALL_KEYS:
        row = stored.get(key)
        if key in SECRET_KEYS:
            result[key] = "********" if (row and row.value) else ""
        elif row and row.value:
            result[key] = row.value
    return result
