"""Redis client + pool helpers.

Two responsibilities live here:

1. ``invalidate_prefix`` — SCAN+UNLINK the ``cache:quiz:list:*`` family
   on every quiz mutation (P04).
2. P05's room-state surface: a ``RoomSnapshotWriter`` that is the
   *single* mutator of ``room:{code}:state``, paired with two tiny Lua
   scripts that make capacity admission and counter-rollback atomic
   even when two API replicas race the same room.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.cache.keys import room_capacity_counter, room_state
from app.db.models.enums import RoomStatus


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


# ---------------------------------------------------------------------------
# Capacity admission — Lua-atomic check-and-increment (P05)
# ---------------------------------------------------------------------------
#
# Two API replicas on the same room would race a Python-side
# ``GET → compare → INCR`` and double-spend the last seat. The script
# runs server-side as a single Redis command so the check and the
# increment are atomic.

# KEYS[1] = room:{code}:participants_count
# ARGV[1] = max_players (int)
# Returns: new count on admit; -1 if at or above capacity (no increment)
CAPACITY_ADMIT_LUA = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur >= tonumber(ARGV[1]) then
  return -1
end
return redis.call('INCR', KEYS[1])
"""

# Compensating decrement on join failure (e.g. duplicate nickname after
# we already admitted the seat). DECR floored at 0 so concurrent
# rollbacks can't push the counter negative.
#
# KEYS[1] = room:{code}:participants_count
# Returns: new count
CAPACITY_RELEASE_LUA = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur <= 0 then
  return 0
end
return redis.call('DECR', KEYS[1])
"""


async def load_capacity_scripts(redis: Redis) -> tuple[str, str]:
    """Load the two capacity scripts; return ``(admit_sha, release_sha)``.

    Called once at startup from ``app.main.lifespan``. SHAs are stashed
    on ``app.state.capacity_admit_sha`` / ``app.state.capacity_release_sha``
    so per-request EVALSHA skips the script-load round-trip.
    """
    admit_sha = await redis.script_load(CAPACITY_ADMIT_LUA)
    release_sha = await redis.script_load(CAPACITY_RELEASE_LUA)
    return admit_sha, release_sha


# ---------------------------------------------------------------------------
# RoomSnapshotWriter — sole mutator of room:{code}:state
# ---------------------------------------------------------------------------
#
# Every write to ``room:{code}:state`` goes through this class. REST
# GET, the WS handshake, and reconnects all read the same JSON blob, so
# a stray writer elsewhere in the codebase would corrupt every consumer
# simultaneously.
#
# TTL strategy: 24h after the room reaches ``completed`` so a finished
# match can still be replayed for analytics, but live rooms persist
# indefinitely (no EX) — letting Redis evict a live lobby would
# desynchronise capacity from the snapshot.

_COMPLETED_TTL_SECONDS = 24 * 60 * 60


class RoomSnapshotWriter:
    """Single mutator of ``room:{code}:state`` plus its capacity counter."""

    def __init__(
        self,
        redis: Redis,
        *,
        admit_sha: str | None = None,
        release_sha: str | None = None,
    ) -> None:
        self.redis = redis
        self.admit_sha = admit_sha
        self.release_sha = release_sha

    # ----- snapshot blob -----

    async def write(
        self, code: str, snapshot: dict[str, Any], *, status: RoomStatus
    ) -> None:
        """JSON-encode ``snapshot`` and SET it under ``room:{code}:state``.

        TTL is set only when the room is ``completed``; live rooms must
        not expire while gameplay is in progress.
        """
        blob = json.dumps(snapshot, separators=(",", ":"))
        if status == RoomStatus.completed:
            await self.redis.set(room_state(code), blob, ex=_COMPLETED_TTL_SECONDS)
        else:
            # PERSIST in case the key previously had a TTL (e.g. cancelled
            # → reopened, or a prior completed run on the same code).
            await self.redis.set(room_state(code), blob)
            await self.redis.persist(room_state(code))

    async def read(self, code: str) -> dict[str, Any] | None:
        raw = await self.redis.get(room_state(code))
        if raw is None:
            return None
        return json.loads(raw)

    # ----- capacity counter -----

    async def participants_count_init(self, code: str, value: int = 0) -> None:
        """Seed the counter on room creation (idempotent SET)."""
        await self.redis.set(room_capacity_counter(code), value)

    async def participants_count_admit(
        self, code: str, max_players: int
    ) -> int:
        """Atomic admission. Returns new count, or ``-1`` if room is full."""
        if self.admit_sha is None:
            raise RuntimeError("RoomSnapshotWriter.admit_sha not configured")
        raw = await self.redis.evalsha(
            self.admit_sha, 1, room_capacity_counter(code), max_players
        )
        return int(raw)

    async def participants_count_release(self, code: str) -> int:
        """Compensating decrement (floor 0)."""
        if self.release_sha is None:
            raise RuntimeError("RoomSnapshotWriter.release_sha not configured")
        raw = await self.redis.evalsha(
            self.release_sha, 1, room_capacity_counter(code)
        )
        return int(raw)
