"""Redis client + pool helpers — filled in P05.

P04's first occupant: ``invalidate_prefix(redis, prefix)`` SCANs and
UNLINKs every key matching ``{prefix}*``. Used to drop the
``cache:quiz:list:*`` family on every quiz mutation. P05 lands the
client-pool wrappers alongside.
"""

from __future__ import annotations

from redis.asyncio import Redis


async def invalidate_prefix(
    redis: Redis, prefix: str, *, batch: int = 500
) -> int:
    """SCAN keys matching ``{prefix}*`` and UNLINK them in batches.

    UNLINK frees memory asynchronously so a SCAN-and-delete burst on a
    large prefix never blocks Redis' main thread. ``batch`` caps the
    SCAN ``COUNT`` hint and the UNLINK pipeline width.
    """
    total = 0
    cursor: int = 0
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor, match=f"{prefix}*", count=batch
        )
        if keys:
            await redis.unlink(*keys)
            total += len(keys)
        if cursor == 0:
            break
    return total
