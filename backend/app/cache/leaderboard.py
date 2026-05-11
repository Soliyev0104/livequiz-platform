"""Live-match leaderboard sorted set (P07).

Backed by ``match:{match_id}:leaderboard`` — a Redis sorted set whose
score is the participant's running total. Two replicas may award
points for two different participants in parallel; ZADD/ZINCRBY are
already atomic per-key in Redis, so no Lua is required for the simple
delta path.

The "increment-with-anchor" path uses a tiny Lua script so the very
first ZADD for a participant binds to their seed score (e.g. 0) without
clobbering a concurrent increment that arrived first. See ``zadd_total``.

Reads return ``(participant_id, score, rank)`` triples sorted by score
DESC. Rank is 1-based and stable for the duration of the read; if scores
change mid-read no consistency guarantee is given (clients see a fresh
broadcast on the next leaderboard update).
"""

from __future__ import annotations

import logging
from typing import Iterable

from redis.asyncio import Redis

from app.cache.keys import match_leaderboard, match_participant_nick

log = logging.getLogger("app.cache.leaderboard")


# KEYS[1] = leaderboard key
# ARGV[1] = participant_id
# ARGV[2] = delta (int)
# Atomic increment-with-init: ZINCRBY adds delta whether or not the
# member existed; the existing-member branch is identical to the
# missing one, so a single Redis call suffices and there is nothing to
# race. Returns the new total as a string.
ZADD_TOTAL_LUA = """
return redis.call('ZINCRBY', KEYS[1], ARGV[2], ARGV[1])
"""


async def load_script(redis: Redis) -> str:
    return await redis.script_load(ZADD_TOTAL_LUA)


async def zadd_total(
    redis: Redis,
    match_id: int | str,
    participant_id: int | str,
    delta: int,
    *,
    sha: str | None = None,
) -> int:
    """Atomically add ``delta`` to ``participant_id``'s score; return new total."""
    key = match_leaderboard(match_id)
    if sha is not None:
        raw = await redis.evalsha(sha, 1, key, str(participant_id), str(int(delta)))
    else:
        raw = await redis.zincrby(key, int(delta), str(participant_id))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


async def mark_answered(
    redis: Redis,
    match_id: int | str,
    question_id: int | str,
    participant_id: int | str,
) -> int:
    """SADD the participant to the per-question answered set; return cardinality."""
    from app.cache.keys import match_answered

    key = match_answered(match_id, question_id)
    pipe = redis.pipeline()
    pipe.sadd(key, str(participant_id))
    pipe.scard(key)
    _, n = await pipe.execute()
    return int(n or 0)


async def answered_count(
    redis: Redis, match_id: int | str, question_id: int | str
) -> int:
    from app.cache.keys import match_answered

    return int(await redis.scard(match_answered(match_id, question_id)) or 0)


async def set_nicknames(
    redis: Redis,
    match_id: int | str,
    pairs: Iterable[tuple[int | str, str]],
) -> None:
    """Bulk HSET participant_id -> nickname so the top-N read can render names."""
    mapping: dict[str, str] = {str(pid): nick for pid, nick in pairs}
    if not mapping:
        return
    await redis.hset(match_participant_nick(match_id), mapping=mapping)


async def get_nickname(
    redis: Redis, match_id: int | str, participant_id: int | str
) -> str | None:
    raw = await redis.hget(match_participant_nick(match_id), str(participant_id))
    return raw if isinstance(raw, str) else None


async def top(
    redis: Redis, match_id: int | str, n: int = 10
) -> list[dict[str, object]]:
    """Return the top ``n`` entries.

    Each row is ``{"rank": 1-based, "participant_id": str, "nickname": str,
    "score": int}``. ``nickname`` may be empty if the hash is missing
    (Redis evicted or the match was reseeded from Postgres).
    """
    key = match_leaderboard(match_id)
    rows: list[tuple[str, float]] = await redis.zrevrange(
        key, 0, max(0, n - 1), withscores=True
    )
    if not rows:
        return []

    nick_key = match_participant_nick(match_id)
    pids = [pid for pid, _ in rows]
    nicks = await redis.hmget(nick_key, *pids) if pids else []

    result: list[dict[str, object]] = []
    for rank, ((pid, score), nick) in enumerate(zip(rows, nicks), start=1):
        result.append(
            {
                "rank": rank,
                "participant_id": str(pid),
                "nickname": nick or "",
                "score": int(score),
            }
        )
    return result


async def reset(redis: Redis, match_id: int | str) -> None:
    """Drop both the sorted set and the nickname hash. Used on match end."""
    await redis.unlink(
        match_leaderboard(match_id), match_participant_nick(match_id)
    )
