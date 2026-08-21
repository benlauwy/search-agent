"""Per-user in-process rate limiting (sliding one-minute window).

Like the run-slot reservation and file version lock, this state lives in
process memory and assumes the documented single-process deployment.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException

WINDOW_SECONDS = 60.0

_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_last_sweep = 0.0


def _sweep(now: float) -> None:
    """Drop buckets whose entries have all expired, so the map doesn't grow
    unboundedly with the number of distinct users."""
    global _last_sweep
    if now - _last_sweep < WINDOW_SECONDS:
        return
    _last_sweep = now
    for key in [k for k, b in _buckets.items() if not b or now - b[-1] > WINDOW_SECONDS]:
        del _buckets[key]


def enforce_rate_limit(action: str, user_id: str, limit: int) -> None:
    """Raise 429 if `user_id` performed `action` more than `limit` times
    in the last minute. A limit <= 0 disables the check."""
    if limit <= 0:
        return
    now = time.monotonic()
    _sweep(now)
    bucket = _buckets[(action, user_id)]
    while bucket and now - bucket[0] > WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = int(WINDOW_SECONDS - (now - bucket[0])) + 1
        raise HTTPException(
            429,
            f"Rate limit exceeded ({limit} {action} per minute). "
            f"Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
