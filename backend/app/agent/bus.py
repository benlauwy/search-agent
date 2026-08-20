"""In-memory pub/sub for streaming run events to SSE subscribers."""

import asyncio
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[session_id].add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        self._subscribers[session_id].discard(q)
        if not self._subscribers[session_id]:
            del self._subscribers[session_id]

    async def publish(self, session_id: str, event: dict) -> None:
        for q in list(self._subscribers.get(session_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Evict the oldest queued event (typically a stale delta) so the
                # newest event always lands; control events like run_finished
                # must reach the client or the UI can get stuck "running".
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


bus = EventBus()
