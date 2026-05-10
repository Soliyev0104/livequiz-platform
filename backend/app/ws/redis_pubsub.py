"""Redis pub/sub fan-out across API replicas (P06).

One pattern subscription per replica covers every room that exists or
will ever exist (``PSUBSCRIBE ws:room:*``). Per-room subscribe/unsubscribe
churn is avoided — Redis pattern matching is O(1) per pmessage and the
single subscription is far cheaper than tracking per-room reference
counts on each WebSocket connect/disconnect.

The listener task is owned by ``app.state.pubsub_task`` and runs for the
lifetime of the FastAPI app. It cancels cleanly on shutdown via
``asyncio.CancelledError`` propagated by ``task.cancel()``.

Loopback suppression: every published message carries
``_origin_replica_id`` (see :mod:`app.ws.connection_manager`). The
listener drops messages that originated on this replica so a single
broadcast does not double-deliver.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.ws.connection_manager import ORIGIN_FIELD, ConnectionManager

log = logging.getLogger("app.ws.redis_pubsub")


WS_ROOM_PATTERN = "ws:room:*"


def _room_code_from_channel(channel: Any) -> str | None:
    """Parse the room code out of a ``ws:room:{code}`` channel name.

    Tolerates both ``str`` and ``bytes`` because ``decode_responses`` can
    differ between the app pool and a test fixture.
    """
    if isinstance(channel, bytes):
        channel = channel.decode("utf-8", errors="replace")
    if not isinstance(channel, str):
        return None
    parts = channel.split(":", 2)
    if len(parts) != 3 or parts[0] != "ws" or parts[1] != "room":
        return None
    return parts[2] or None


async def _dispatch_one(
    manager: ConnectionManager,
    msg: dict[str, Any],
) -> None:
    channel = msg.get("channel")
    code = _room_code_from_channel(channel)
    if code is None:
        return
    raw = msg.get("data")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("dropping malformed pub/sub message on %s", channel)
        return
    if not isinstance(payload, dict):
        return
    # Drop our own loopback. Other replicas' messages still carry their
    # origin id; ``broadcast_local`` strips it before sending to clients.
    origin = payload.get(ORIGIN_FIELD)
    if origin == manager.replica_id:
        return
    await manager.broadcast_local(code, payload)


async def run_pubsub_listener(
    redis: Redis,
    manager: ConnectionManager,
    *,
    ready: asyncio.Event | None = None,
) -> None:
    """Long-running task: psubscribe ``ws:room:*`` and dispatch forever.

    ``ready`` (if provided) is set after the subscription is confirmed
    live, which the integration tests use to avoid racing the listener
    with their first publish.
    """
    pubsub = redis.pubsub()
    try:
        await pubsub.psubscribe(WS_ROOM_PATTERN)
        if ready is not None:
            ready.set()
        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if msg is None:
                continue
            if msg.get("type") not in {"pmessage", "message"}:
                continue
            try:
                await _dispatch_one(manager, msg)
            except Exception as exc:  # noqa: BLE001 — one bad message must not kill the loop
                log.exception("pubsub dispatch failed: %s", exc)
    except asyncio.CancelledError:
        raise
    finally:
        with contextlib.suppress(Exception):
            await pubsub.punsubscribe(WS_ROOM_PATTERN)
        with contextlib.suppress(Exception):
            await pubsub.aclose()


async def start_pubsub_task(
    redis: Redis,
    manager: ConnectionManager,
) -> tuple[asyncio.Task[None], asyncio.Event]:
    """Spawn the listener; resolve once the subscription is live.

    Returning the ready event lets the lifespan await it before yielding
    so the very first request after startup is guaranteed cross-replica.
    """
    ready = asyncio.Event()
    task = asyncio.create_task(
        run_pubsub_listener(redis, manager, ready=ready),
        name="ws-pubsub-listener",
    )
    try:
        await asyncio.wait_for(ready.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        log.warning("pubsub subscription did not confirm within 5s")
    return task, ready


async def stop_pubsub_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
