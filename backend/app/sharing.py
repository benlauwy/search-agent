from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatSession


async def is_shared(db: AsyncSession, session: ChatSession) -> bool:
    """A session is readable by non-owners if it is shared, or if it is a
    subagent session whose parent is shared (subagents are depth 1)."""
    if session.shared:
        return True
    if session.parent_session_id:
        parent = await db.get(ChatSession, session.parent_session_id)
        return parent is not None and parent.shared
    return False
