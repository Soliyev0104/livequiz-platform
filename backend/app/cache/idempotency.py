"""``X-Request-ID`` idempotency cache.

A retried answer-submission must yield exactly the same response that
the original request produced — even if the original is still in flight.
This module is the cache half of that contract:

- :func:`get` reads ``idem:{request_id}`` and returns the JSON-decoded
  response (or ``None`` on miss).
- :func:`set` writes the response with ``SET NX EX 86400``. ``NX`` is
  the race breaker: if two concurrent retries both miss the cache and
  both reach the DB, the second one to attempt ``set`` will be a no-op
  and the first stored response wins — symmetric with the unique-index
  fallback in the answer-submission tx.

The DB-level ``ux_submission_request`` is the durable safety net; this
cache exists so a hot retry path skips the DB transaction entirely.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.cache.keys import idempotency_key

log = logging.getLogger("app.cache.idempotency")

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60  # 24h, per docs/09


async def get(redis: Redis, request_id: str) -> dict[str, Any] | None:
    raw = await redis.get(idempotency_key(request_id))
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as exc:
        log.warning("malformed idempotency payload for %s: %s", request_id, exc)
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


async def set(
    redis: Redis,
    request_id: str,
    response: dict[str, Any],
    *,
    ttl_seconds: int = IDEMPOTENCY_TTL_SECONDS,
) -> bool:
    """Store ``response`` under ``idem:{request_id}`` if not already present.

    Returns True when this call wrote the value (cache miss path),
    False if another writer beat us to it (concurrent-retry path).
    """
    blob = json.dumps(response, separators=(",", ":"), default=str)
    ok = await redis.set(
        idempotency_key(request_id),
        blob,
        nx=True,
        ex=int(ttl_seconds),
    )
    return bool(ok)
