"""Per-process WebSocket connection registry (P06).

Each FastAPI replica owns one ``ConnectionManager`` instance, stashed on
``app.state.connection_manager`` during the lifespan startup. The map is
``dict[room_code, set[WebSocketConnection]]``: rooms come and go as
connections enter and leave, and an empty ``room_code`` entry is pruned
on the last disconnect.

Why per-connection ``send_lock``: Starlette buffers a single in-flight
``send`` per WebSocket. Two coroutines hitting the same ``ws.send_json``
concurrently raise ``RuntimeError: cannot call recv while another
coroutine is already running recv`` (and the symmetric send-side variant
on some Python versions). The lock serialises every outgoing write per
socket. Locks are never held while iterating other connections, so a
slow client cannot back-pressure the whole room.

Cross-replica fan-out is done by :func:`broadcast_all`. It publishes the
payload to ``ws:room:{code}`` AND delivers locally so the originating
replica's clients see it without a Redis round-trip. To prevent the
local-and-published delivery from double-fanning the message back via
the pub/sub listener, ``broadcast_all`` stamps the published copy with
``_origin_replica_id``; the listener (in :mod:`app.ws.redis_pubsub`)
suppresses messages tagged with its own replica id and strips the field
before forwarding to clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from redis.asyncio import Redis

from app.cache.keys import ws_room

log = logging.getLogger("app.ws.connection_manager")


# Internal pub/sub field used to tag a message with its originating
# replica id so the cross-replica listener can skip its own loopback.
ORIGIN_FIELD = "_origin_replica_id"


# Application-defined close code used by the P09 mute decision path.
# The synthetic ``participant.kicked`` envelope arrives via pub/sub and
# the manager translates it into a per-socket close on the matching
# participant id.
KICKED_CLOSE_CODE = 4002


# ---------------------------------------------------------------------------
# Connection record
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class WebSocketConnection:
    """One live WebSocket attached to a room.

    ``eq=False`` so identity-based hashing remains in place — connections
    are stored in :class:`set` and a duplicate ``conn_id`` would otherwise
    silently collide. ``last_seen`` is a ``time.monotonic()`` timestamp
    so the heartbeat watchdog never confuses a system-clock jump with
    silence.
    """

    ws: WebSocket
    conn_id: str
    participant_id: int
    nickname: str
    is_host: bool
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: float = field(default_factory=time.monotonic)

    async def send(self, message: dict[str, Any]) -> bool:
        """Serialise and send ``message`` under the per-socket lock.

        Returns False on transport failure so the caller can deregister
        the connection. We log at INFO (not ERROR) because a closing
        client during fan-out is normal traffic.
        """
        try:
            async with self.send_lock:
                await self.ws.send_text(json.dumps(message, separators=(",", ":")))
            return True
        except Exception as exc:  # noqa: BLE001 — network errors must not kill the broadcast loop
            log.info("ws send failed conn=%s: %s", self.conn_id, exc)
            return False


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """In-process map of ``room_code → set[WebSocketConnection]``."""

    def __init__(self, *, replica_id: str) -> None:
        self.replica_id = replica_id
        self._rooms: dict[str, set[WebSocketConnection]] = {}
        # Lazily initialised; if the manager is constructed off-loop and
        # later used inside an asyncio loop, ``asyncio.Lock()`` would
        # otherwise bind to the wrong loop.
        self._mutate_lock: asyncio.Lock | None = None

    def _lock(self) -> asyncio.Lock:
        if self._mutate_lock is None:
            self._mutate_lock = asyncio.Lock()
        return self._mutate_lock

    # ----- registry -----

    async def connect(self, room_code: str, conn: WebSocketConnection) -> None:
        async with self._lock():
            self._rooms.setdefault(room_code, set()).add(conn)

    async def disconnect(self, room_code: str, conn: WebSocketConnection) -> bool:
        """Remove ``conn`` from the room. Returns True if room is now empty."""
        async with self._lock():
            members = self._rooms.get(room_code)
            if members is None:
                return True
            members.discard(conn)
            if not members:
                self._rooms.pop(room_code, None)
                return True
            return False

    def members(self, room_code: str) -> list[WebSocketConnection]:
        """Snapshot of current room members; safe to iterate without locks."""
        return list(self._rooms.get(room_code, ()))

    def room_count(self) -> int:
        return len(self._rooms)

    # ----- broadcast -----

    async def broadcast_local(
        self, room_code: str, message: dict[str, Any]
    ) -> int:
        """Deliver ``message`` to every connection in ``room_code`` on this replica.

        The synthetic ``participant.kicked`` envelope (emitted by the P09
        moderation mute path) is treated specially: every member in the
        room receives the informational frame, and the connection whose
        ``participant_id`` matches the payload is closed with
        ``KICKED_CLOSE_CODE`` so the client transport teardown is
        observable from the kicked participant's side.
        """
        clean = {k: v for k, v in message.items() if k != ORIGIN_FIELD}
        members = self.members(room_code)
        if not members:
            return 0
        # Per-connection sends in parallel; one slow socket can't stall others.
        results = await asyncio.gather(
            *(conn.send(clean) for conn in members), return_exceptions=False
        )
        delivered = sum(1 for ok in results if ok)

        if clean.get("type") == "participant.kicked":
            await self._close_kicked(room_code, clean)
        return delivered

    async def _close_kicked(
        self, room_code: str, message: dict[str, Any]
    ) -> None:
        """Close every connection in ``room_code`` whose participant_id matches.

        Tolerates string/int ``participant_id`` because tokens encode the
        snowflake as a string but the connection record keeps it as int.
        Multiple sockets per participant (rare — duplicate tabs) all close.
        """
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        raw_pid = payload.get("participant_id")
        try:
            target_pid = int(raw_pid)
        except (TypeError, ValueError):
            return
        for conn in self.members(room_code):
            if conn.participant_id != target_pid:
                continue
            try:
                await conn.ws.close(code=KICKED_CLOSE_CODE, reason="muted")
            except Exception as exc:  # noqa: BLE001 — close is best-effort
                log.info(
                    "ws close-on-kick failed conn=%s: %s", conn.conn_id, exc
                )

    async def broadcast_all(
        self,
        redis: Redis,
        room_code: str,
        message: dict[str, Any],
    ) -> None:
        """Fan out ``message`` to every replica's clients.

        Published copy carries ``_origin_replica_id`` so this replica's
        own pub/sub listener can drop the loopback. The local fan-out
        happens unconditionally so the originating replica has no extra
        latency.
        """
        wire = {**message, ORIGIN_FIELD: self.replica_id}
        try:
            await redis.publish(
                ws_room(room_code),
                json.dumps(wire, separators=(",", ":")),
            )
        except Exception as exc:  # noqa: BLE001 — Redis hiccup must not blank local fan-out
            log.warning("redis publish failed room=%s: %s", room_code, exc)
        await self.broadcast_local(room_code, message)
