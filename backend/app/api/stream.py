import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from ..agent import runner
from ..agent.bus import bus
from ..models import ChatSession
from .sessions import get_owned_session

router = APIRouter(prefix="/api/sessions", tags=["stream"])


@router.get("/{session_id}/stream")
async def stream(
    request: Request,
    session: ChatSession = Depends(get_owned_session),
):
    session_id = session.id

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
