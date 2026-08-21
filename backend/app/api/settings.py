from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.routes import get_current_user
from ..db import get_db
from ..models import User
from ..settings_store import ALL_KEYS, SECRET_KEYS, get_all_settings, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    values: dict[str, str]


@router.get("")
async def read_settings(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return {
        "values": await get_all_settings(db),
        "secret_keys": sorted(SECRET_KEYS),
    }


@router.put("")
async def update_settings(
    body: UpdateSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for key, value in body.values.items():
        if key not in ALL_KEYS:
            continue
        if key in SECRET_KEYS and value == "********":
            continue  # masked placeholder, unchanged
        await set_setting(db, key, value)
    return {"values": await get_all_settings(db)}
