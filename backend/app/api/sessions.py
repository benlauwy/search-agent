import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent import runner
from ..auth.routes import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import ChatSession, Event, Message, User, _now
from ..providers.registry import PROVIDERS
from ..ratelimit import enforce_rate_limit
from ..settings_store import get_setting
from ..sharing import is_shared

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    provider: str = ""
    model: str = ""


class SendMessageRequest(BaseModel):
    text: str


class UpdateSessionRequest(BaseModel):
    provider: str = ""
    model: str | None = None
    shared: bool | None = None


async def get_owned_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found")
    return session


async def get_readable_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSession:
    """Owner gets full access; any authenticated user may read a shared session.
    Subagent sessions inherit shared visibility from their parent (depth 1)."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    if session.user_id != user.id and not await is_shared(db, session):
        raise HTTPException(404, "Session not found")
    return session


def _session_dict(s: ChatSession, user_id: str | None = None) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "provider": s.provider,
        "model": s.model,
        "kind": s.kind,
        "shared": s.shared,
        "owned": user_id is None or s.user_id == user_id,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


@router.get("")
async def list_sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.user_id == user.id, ChatSession.kind == "chat")
                .order_by(ChatSession.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_session_dict(s) for s in rows]


@router.post("")
async def create_session(
    body: CreateSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    provider = body.provider or await get_setting(db, "default_provider")
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")
    session = ChatSession(user_id=user.id, provider=provider, model=body.model)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_dict(session)


@router.get("/{session_id}")
async def get_session(
    session: ChatSession = Depends(get_readable_session),
    user: User = Depends(get_current_user),
):
    return _session_dict(session, user.id)


@router.patch("/{session_id}")
async def update_session(
    body: UpdateSessionRequest,
    session: ChatSession = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    """Change provider/model for a session. Providers may only switch between
    runs — mid-tool-loop switches would break reasoning continuity."""
    if runner.is_running(session.id):
        raise HTTPException(409, "Cannot change provider while a run is in progress")
    if body.provider:
        if body.provider not in PROVIDERS:
            raise HTTPException(400, f"Unknown provider: {body.provider}")
        if body.provider != session.provider:
            session.provider = body.provider
            # Model names are provider-specific; a stale override would fail
            # on the new provider, so reset to the provider default.
            if body.model is None:
                session.model = ""
    if body.model is not None:
        session.model = body.model
    if body.shared is not None:
        session.shared = body.shared
    await db.commit()
    await db.refresh(session)
    return _session_dict(session)


@router.delete("/{session_id}")
async def delete_session(
    session: ChatSession = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    from ..models import File

    file_paths: list[str] = []

    async def delete_one(target: ChatSession) -> None:
        await runner.stop_run(target.id)
        children = (
            (
                await db.execute(
                    select(ChatSession).where(ChatSession.parent_session_id == target.id)
                )
            )
            .scalars()
            .all()
        )
        for child in children:
            await delete_one(child)
        for model in (Message, Event, File):
            rows = (
                (await db.execute(select(model).where(model.session_id == target.id)))
                .scalars()
                .all()
            )
            for r in rows:
                if model is File and r.path:
                    file_paths.append(r.path)
                await db.delete(r)
        await db.flush()
        await db.delete(target)

    await delete_one(session)
    await db.commit()
    for path in file_paths:
        try:
            os.unlink(path)
        except OSError:
            pass
    return {"ok": True}


@router.get("/{session_id}/messages")
async def list_messages(
    session: ChatSession = Depends(get_readable_session),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(Message).where(Message.session_id == session.id).order_by(Message.idx)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": m.id,
            "idx": m.idx,
            "role": m.role,
            "text": m.text,
            "reasoning": [
                b.get("display_text", "") for b in (m.reasoning_json or []) if b.get("display_text")
            ],
            "tool_calls": m.tool_calls_json or [],
            "tool_call_id": m.tool_call_id,
            "tool_name": m.tool_name,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.post("/{session_id}/messages")
async def send_message(
    body: SendMessageRequest,
    session: ChatSession = Depends(get_owned_session),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty message")
    enforce_rate_limit("runs", user.id, get_settings().rate_limit_runs_per_minute)
    if not runner.try_reserve_run(session.id):
        raise HTTPException(409, "A run is already in progress for this session")
    try:
        idx = (
            await db.execute(
                select(func.coalesce(func.max(Message.idx), -1)).where(
                    Message.session_id == session.id
                )
            )
        ).scalar_one() + 1
        db.add(Message(session_id=session.id, idx=idx, role="user", text=text))
        if session.title == "New chat":
            session.title = text[:80]
        session.updated_at = _now()
        await db.commit()
        run_id = runner.start_run(session.id, user.id)
    except BaseException:
        runner.release_run_reservation(session.id)
        raise
    return {"run_id": run_id}


@router.post("/{session_id}/cancel")
async def cancel(session: ChatSession = Depends(get_owned_session)):
    return {"cancelled": runner.cancel_run(session.id)}


@router.get("/{session_id}/events")
async def list_events(
    session: ChatSession = Depends(get_readable_session),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(Event)
                .where(Event.session_id == session.id)
                .order_by(Event.created_at, Event.idx)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": e.id,
            "run_id": e.run_id,
            "idx": e.idx,
            "type": e.type,
            "payload": e.payload_json,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]
