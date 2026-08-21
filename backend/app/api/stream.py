import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..agent import runner
from ..agent.bus import bus
from ..auth.routes import get_current_user
from ..db import SessionLocal
from ..models import ChatSession
from ..sharing import is_shared

router = APIRouter(prefix="/api/sessions", tags=["stream"])


@router.get("/{session_id}/stream")
async def stream(session_id: str, request: Request):
    # Ownership check with a short-lived DB session: the SSE response is
    # long-lived and must not pin a pooled connection for its duration.
    async with SessionLocal() as db:
        user = await get_current_user(request, db)
        session = await db.get(ChatSession, session_id)
        if session is None or (session.user_id != user.id and not await is_shared(db, session)):
            raise HTTPException(404, "Session not found")

    async def generator():
        q = bus.subscribe(session_id)
        try:
            yield {
                "event": "status",
                "data": json.dumps({"running": runner.is_running(session_id)}),
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": event["type"], "data": json.dumps(event)}
        finally:
            bus.unsubscribe(session_id, q)

    return EventSourceResponse(generator())
