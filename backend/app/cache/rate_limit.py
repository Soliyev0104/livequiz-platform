"""Atomic Redis token-bucket rate limiter.

The Lua script runs entirely server-side so check-and-decrement races
between API replicas can't double-spend a token. Loaded once at app
startup via ``redis.script_load`` (see ``app.main.lifespan``); the SHA is
stashed on ``app.state.rate_limit_sha`` and passed in to ``acquire``.

Used in P03 by the login endpoint (``rate:login:{ip}:{sha1(email)}``);
P05+ phases will reuse for `/rooms/{code}/join`, answer submission, and WS
message gates.

Bucket state lives at one Redis hash per ``key``:

    HSET <key> tokens <float> ts_ms <int>
    PEXPIRE <key> <bucket-ttl-ms>

`bucket-ttl-ms` is `ceil(capacity / refill_per_sec) + 1` seconds — long
enough that an idle bucket can be regenerated to full capacity, short
enough to garbage-collect inactive keys.
"""

from __future__ import annotations

import math

from redis.asyncio import Redis

# ``KEYS[1]`` = bucket key
# ``ARGV`` = capacity, refill_per_sec, cost, now_ms, ttl_ms
#
# Returns ``{allowed (0|1), remaining (int), retry_after_ms (int)}``.
RATE_LIMIT_LUA = """
local key            = KEYS[1]
local capacity       = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local cost           = tonumber(ARGV[3])
local now_ms         = tonumber(ARGV[4])
local ttl_ms         = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'ts_ms')
local tokens = tonumber(data[1])
local ts_ms  = tonumber(data[2])

if tokens == nil or ts_ms == nil then
  tokens = capacity
  ts_ms  = now_ms
else
  local delta_ms = now_ms - ts_ms
  if delta_ms < 0 then delta_ms = 0 end
  tokens = math.min(capacity, tokens + delta_ms * refill_per_sec / 1000.0)
  ts_ms  = now_ms
end

local allowed = 0
local retry_after_ms = 0

if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  local missing = cost - tokens
  retry_after_ms = math.ceil(missing * 1000.0 / refill_per_sec)
end

redis.call('HSET', key, 'tokens', tokens, 'ts_ms', ts_ms)
redis.call('PEXPIRE', key, ttl_ms)

return {allowed, math.floor(tokens), retry_after_ms}
"""


async def load_script(redis: Redis) -> str:
    """Load the Lua script and return its SHA1 hash for later EVALSHA calls."""
    sha = await redis.script_load(RATE_LIMIT_LUA)
    return sha


async def acquire(
    redis: Redis,
    sha: str,
    key: str,
    *,
    capacity: int,
    refill_per_sec: float,
    cost: int = 1,
    now_ms: int | None = None,
) -> tuple[bool, int, int]:
    """Try to spend ``cost`` tokens from the bucket at ``key``.

    Returns ``(allowed, remaining, retry_after_ms)``.
    ``retry_after_ms`` is 0 when ``allowed`` is True.
    """
    import time as _time

    if now_ms is None:
        now_ms = int(_time.time() * 1000)

    ttl_ms = int(math.ceil(capacity / refill_per_sec) * 1000) + 1000

    raw = await redis.evalsha(
        sha,
        1,
        key,
        capacity,
        refill_per_sec,
        cost,
        now_ms,
        ttl_ms,
    )
    allowed = bool(int(raw[0]))
    remaining = int(raw[1])
    retry_after_ms = int(raw[2])
    return allowed, remaining, retry_after_ms
