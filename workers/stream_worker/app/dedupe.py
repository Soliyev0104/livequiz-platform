"""Redis-backed event-id dedupe.

Stream worker reads at-least-once: Kafka offset is only committed after
the side effects succeed, so a crash mid-batch causes a redelivery. We
ride two lines of defense:

1. ``seen:event:{event_id}`` set with SET NX EX 86400 — short-circuits
   handlers in <1 ms when a duplicate arrives.
2. ClickHouse ``ReplacingMergeTree`` on ``answer_events`` merges
   duplicates with the same ``(match_id, question_id, participant_id,
   event_id)`` tuple offline.

Layer #1 stops the inserts from happening at all in the steady state;
layer #2 keeps answer-events idempotent even if Redis is wiped.
"""

from __future__ import annotations

from redis.asyncio import Redis


SEEN_KEY = "seen:event:{event_id}"
SEEN_TTL_SECONDS = 86_400  # 24 h — well past any plausible redelivery window


async def claim(redis: Redis, event_id: str | int) -> bool:
    """Return True if this is the first time we've seen ``event_id``.

    Internally uses ``SET key value NX EX ttl``; the boolean reply is
    ``True`` only when the key was just created. The chosen TTL is the
    upper bound on how long Kafka would keep redelivering a single
    message before the consumer group rolls past it; 24 h is generous.
    """
    key = SEEN_KEY.format(event_id=event_id)
    res = await redis.set(key, "1", nx=True, ex=SEEN_TTL_SECONDS)
    return bool(res)
