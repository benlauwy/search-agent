from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_url = get_settings().database_url
# SQLite allows one writer at a time; a busy timeout makes concurrent
# short write transactions (events/messages from parallel tool calls)
# queue instead of raising "database is locked".
_connect_args = {"timeout": 30} if _url.startswith("sqlite") else {}
engine = create_async_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
