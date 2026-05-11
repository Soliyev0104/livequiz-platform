"""WebSocket endpoint ``/ws/rooms/{room_code}`` (P06).

Lifecycle per connection:

  1. Parse ``?token=...`` from the query string. **Validate before
     ``ws.accept()``** — an unauthorised client should see a rejection
     handshake, not a closed-after-accept frame, so logs do not lie
     about which connections were authorised. Token must be a P05
     participant-typed JWT whose ``room_code`` matches the path; the
     token's ``participant_id == room.host_id`` distinguishes host from
     player.
  2. Accept and immediately push ``room.snapshot`` (Redis-first via
     :func:`app.services.room_service.build_snapshot`).
  3. Register in :class:`ConnectionManager` and announce
     ``participant.joined`` to the room.
  4. Receive loop with a 60s server-side heartbeat watchdog. Per-message
     rate limit: 30 ops / sec / connection. ``answer.submit`` adds a
     soft 5 / (participant, match_question_id) gate.
  5. On disconnect, deregister and broadcast ``participant.left``. The
     pattern subscription on ``ws:room:*`` is per-replica, so no
     per-room unsubscribe is required.

Heartbeat semantics: server is the timeout authority — it closes 4001
after 60s of silence. The server also responds to every client
``room.heartbeat`` with ``room.heartbeat.ack`` carrying ``server_now``
so the client can derive clock skew.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cache.rate_limit import acquire as rate_acquire
from app.core.config import get_settings
from app.core.ids import get_id_generator
from app.core.metrics import ws_connections_active
from app.core.security import (
    PARTICIPANT_TYPE,
    AuthError,
    decode_token,
)
from app.repositories.room_repo import RoomRepo
from app.services import room_service
from app.ws.connection_manager import ConnectionManager, WebSocketConnection
from app.ws.messages import (
    AnswerSubmitMessage,
    ClientMessageAdapter,
    HeartbeatMessage,
    HostMatchPauseMessage,
    HostQuestionNextMessage,
    server_now_iso,
)

log = logging.getLogger("app.ws.router")
router = APIRouter()


HEARTBEAT_TIMEOUT_S = 60.0
WS_RATE_CAPACITY = 30
WS_RATE_REFILL = 30  # tokens / sec
ANSWER_RATE_LIMIT = 5
ANSWER_RATE_TTL_S = 600

# WebSocket close codes — application-defined 4xxx range.
CLOSE_UNAUTHORIZED = 4401
CLOSE_HEARTBEAT_TIMEOUT = 4001
CLOSE_NORMAL = 1000


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def _authenticate(
    ws: WebSocket,
    room_code: str,
    redis: Redis,
    sessionmaker: async_sessionmaker,
) -> tuple[int, str, bool] | None:
    """Validate the participant token. Returns ``(participant_id, nickname, is_host)``.

    Returns ``None`` after closing the WebSocket with 4401 on any
    failure. Caller must short-circuit. ``ws.accept`` MUST NOT have run
    when this returns ``None``.
    """
    token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="missing token")
        return None

    settings = get_settings()
    try:
        claims = decode_token(token, PARTICIPANT_TYPE, settings.jwt_secret)
    except AuthError:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="invalid token")
        return None

    if str(claims.get("room_code")) != room_code:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="room mismatch")
        return None

    try:
        participant_id = int(claims["participant_id"])
    except (KeyError, TypeError, ValueError):
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="malformed token")
        return None
    nickname = str(claims.get("nickname") or "")

    # Confirm the room still exists and decide host-vs-player.
    async with sessionmaker() as session:
        room = await RoomRepo(session).get_by_code(room_code)
    if room is None:
        await ws.close(code=CLOSE_UNAUTHORIZED, reason="room not found")
        return None

    is_host = participant_id == room.host_id
    return participant_id, nickname, is_host


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


async def _ws_rate_check(
    redis: Redis, rate_sha: str, conn_id: str
) -> tuple[bool, int]:
    """Per-connection 30/sec gate. Returns ``(allowed, retry_after_ms)``."""
    allowed, _remaining, retry_after_ms = await rate_acquire(
        redis,
        rate_sha,
        f"rate:ws:{conn_id}",
        capacity=WS_RATE_CAPACITY,
        refill_per_sec=WS_RATE_REFILL,
        cost=1,
    )
    return allowed, retry_after_ms


async def _answer_rate_check(
    redis: Redis, participant_id: int, match_question_id: str
) -> bool:
    """Soft per-(participant, question) cap of 5 attempts.

    Independent of the per-connection 30/sec bucket so a client cannot
    burst-spam answers for a single question even if its overall WS
    rate is healthy. Implemented as INCR+EXPIRE rather than the token
    bucket because we want a hard ceiling that does not refill within
    the question lifetime.
    """
    key = f"rate:ws:answer:{participant_id}:{match_question_id}"
    val = await redis.incr(key)
    if val == 1:
        await redis.expire(key, ANSWER_RATE_TTL_S)
    return val <= ANSWER_RATE_LIMIT


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/rooms/{room_code}")
async def ws_room_endpoint(websocket: WebSocket, room_code: str) -> None:
    app = websocket.app
    state = app.state

    redis_pool = state.redis_pool
    engine = state.engine
    manager: ConnectionManager = state.connection_manager
    rate_sha: str = state.rate_limit_sha
    admit_sha: str = state.capacity_admit_sha
    release_sha: str = state.capacity_release_sha
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    redis = Redis(connection_pool=redis_pool)
    try:
        auth = await _authenticate(websocket, room_code, redis, sessionmaker)
        if auth is None:
            return
        participant_id, nickname, is_host = auth

        await websocket.accept()

        # Build and send the initial snapshot. A failure here does not
        # poison the connection — we close cleanly so the client retries.
        try:
            async with sessionmaker() as session:
                snapshot_payload = await room_service.build_snapshot(
                    session,
                    redis,
                    code=room_code,
                    admit_sha=admit_sha,
                    release_sha=release_sha,
                )
        except AuthError as exc:
            await _send(
                websocket,
                {
                    "type": "error",
                    "payload": {"code": exc.code, "message": exc.message or ""},
                },
            )
            await websocket.close(code=CLOSE_NORMAL)
            return

        gen = get_id_generator()
        await _send(
            websocket,
            {
                "type": "room.snapshot",
                "message_id": str(gen.next_id()),
                "payload": snapshot_payload,
            },
        )

        # Read player_count before any try/finally that references it so
        # an exception above never leaves it unbound when the leave-event
        # broadcast tries to subtract from it.
        player_count = 0
        room_block = snapshot_payload.get("room") if isinstance(snapshot_payload, dict) else None
        if isinstance(room_block, dict):
            pc = room_block.get("player_count")
            if isinstance(pc, int):
                player_count = pc

        conn = WebSocketConnection(
            ws=websocket,
            conn_id=uuid.uuid4().hex,
            participant_id=participant_id,
            nickname=nickname,
            is_host=is_host,
        )
        await manager.connect(room_code, conn)
        ws_connections_active.inc()

        try:
            # Announce arrival to the room (cross-replica). The host
            # also gets a join event so client UIs can render presence
            # uniformly — branching on ``is_host`` is a UI concern.
            await manager.broadcast_all(
                redis,
                room_code,
                {
                    "type": "participant.joined",
                    "message_id": str(gen.next_id()),
                    "payload": {
                        "participant_id": str(participant_id),
                        "nickname": nickname,
                        "player_count": player_count,
                    },
                },
            )

            watchdog = asyncio.create_task(
                _heartbeat_watchdog(websocket, conn),
                name=f"ws-watchdog-{conn.conn_id}",
            )
            try:
                await _receive_loop(
                    websocket,
                    conn,
                    room_code,
                    redis,
                    manager,
                    rate_sha,
                )
            finally:
                watchdog.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError, Exception
                ):
                    await watchdog
        finally:
            ws_connections_active.dec()
            await manager.disconnect(room_code, conn)
            try:
                await manager.broadcast_all(
                    redis,
                    room_code,
                    {
                        "type": "participant.left",
                        "message_id": str(gen.next_id()),
                        "payload": {
                            "participant_id": str(participant_id),
                            "nickname": nickname,
                            "player_count": max(0, player_count - 1),
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001 — best-effort departure notice
                log.info("participant.left broadcast failed: %s", exc)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001 — pool cleanup is best-effort
            pass


# ---------------------------------------------------------------------------
# Receive loop
# ---------------------------------------------------------------------------


async def _send(ws: WebSocket, message: dict[str, Any]) -> None:
    await ws.send_json(message)


async def _heartbeat_watchdog(
    ws: WebSocket, conn: WebSocketConnection
) -> None:
    """Close ``ws`` with 4001 if the client falls silent for HEARTBEAT_TIMEOUT_S.

    Implemented as a side-task so the receive loop can block indefinitely
    on ``ws.receive_text()`` without ``asyncio.wait_for`` — the latter
    breaks under ASGI test transports that run the app inside an anyio
    task group, raising ``RuntimeError: Attempted to exit cancel scope
    in a different task than it was entered in`` when the wait fires.
    """
    poll_interval = 5.0
    while True:
        try:
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            return
        if time.monotonic() - conn.last_seen > HEARTBEAT_TIMEOUT_S:
            with contextlib.suppress(Exception):
                await ws.close(
                    code=CLOSE_HEARTBEAT_TIMEOUT, reason="heartbeat timeout"
                )
            return


async def _receive_loop(
    ws: WebSocket,
    conn: WebSocketConnection,
    room_code: str,
    redis: Redis,
    manager: ConnectionManager,
    rate_sha: str,
) -> None:
    """Block on the WS until disconnect. Heartbeat enforcement runs as a
    sibling watchdog task created by ``ws_room_endpoint``.
    """
    while True:
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            return
        except RuntimeError:
            # Starlette raises ``RuntimeError`` if ``receive`` is called
            # after the socket has been closed by another coroutine
            # (e.g. the watchdog firing). Treat as graceful disconnect.
            return

        conn.last_seen = time.monotonic()

        # Per-connection rate cap: 30 ops/sec, hard.
        allowed, retry_after_ms = await _ws_rate_check(
            redis, rate_sha, conn.conn_id
        )
        if not allowed:
            await conn.send(
                {
                    "type": "error",
                    "payload": {
                        "code": "RATE_LIMITED",
                        "message": "ws message rate exceeded",
                        "retry_after_ms": int(retry_after_ms),
                    },
                }
            )
            continue

        try:
            message = ClientMessageAdapter.validate_json(raw)
        except ValidationError as exc:
            await conn.send(
                {
                    "type": "error",
                    "payload": {
                        "code": "VALIDATION_ERROR",
                        "message": "invalid message",
                        "retry_after_ms": None,
                    },
                }
            )
            log.info("ws validation_error conn=%s: %s", conn.conn_id, exc.errors())
            continue
        except ValueError:
            await conn.send(
                {
                    "type": "error",
                    "payload": {
                        "code": "VALIDATION_ERROR",
                        "message": "malformed json",
                        "retry_after_ms": None,
                    },
                }
            )
            continue

        await _dispatch(message, conn, room_code, redis, manager)


async def _dispatch(
    message: Any,
    conn: WebSocketConnection,
    room_code: str,
    redis: Redis,
    manager: ConnectionManager,
) -> None:
    if isinstance(message, HeartbeatMessage):
        await conn.send(
            {
                "type": "room.heartbeat.ack",
                "message_id": message.message_id,
                "payload": {
                    "server_now": server_now_iso(),
                    "last_seen_event_id": message.payload.last_seen_event_id,
                },
            }
        )
        return

    if isinstance(message, AnswerSubmitMessage):
        ok = await _answer_rate_check(
            redis, conn.participant_id, message.payload.match_question_id
        )
        if not ok:
            await conn.send(
                {
                    "type": "error",
                    "payload": {
                        "code": "RATE_LIMITED",
                        "message": "answer attempts exceeded",
                        "retry_after_ms": None,
                    },
                }
            )
            return
        await _ws_submit_answer(message, conn)
        return

    if isinstance(message, (HostQuestionNextMessage, HostMatchPauseMessage)):
        if not conn.is_host:
            await conn.send(
                {
                    "type": "error",
                    "payload": {
                        "code": "FORBIDDEN",
                        "message": "host-only message",
                        "retry_after_ms": None,
                    },
                }
            )
            return
        # Host control surface lives at the REST endpoints
        # (POST /rooms/{code}/{pause,resume,next,end}). The WS messages
        # are advisory hints only — clients should call REST.
        await conn.send(
            {
                "type": "error",
                "payload": {
                    "code": "NOT_IMPLEMENTED",
                    "message": "use REST host-control endpoints",
                    "retry_after_ms": None,
                },
            }
        )
        return

    log.warning("ws unhandled message type=%s conn=%s", type(message).__name__, conn.conn_id)


async def _ws_submit_answer(
    message: AnswerSubmitMessage, conn: WebSocketConnection
) -> None:
    """Bridge the WS ``answer.submit`` payload into the P07 service.

    The service owns idempotency, scoring, the outbox, and the
    leaderboard broadcast. Here we only translate the WS envelope to
    the service signature and push a private ``answer.accepted`` ack
    back to this connection. Errors land on the client as ``error``
    envelopes carrying the documented error codes.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.security import AuthError
    from app.schemas.match import AnswerSubmitRequest
    from app.services import match_service

    app = conn.ws.app
    runtime: match_service.MatchRuntime | None = getattr(
        app.state, "match_runtime", None
    )
    if runtime is None:
        await conn.send(
            {
                "type": "error",
                "message_id": message.message_id,
                "payload": {
                    "code": "INTERNAL_ERROR",
                    "message": "match runtime not initialised",
                },
            }
        )
        return

    try:
        match_id = int(message.payload.match_id)
        match_question_id = int(message.payload.match_question_id)
        selected_ids = [int(x) for x in message.payload.selected_option_ids]
    except (TypeError, ValueError):
        await conn.send(
            {
                "type": "error",
                "message_id": message.message_id,
                "payload": {
                    "code": "VALIDATION_ERROR",
                    "message": "invalid id in payload",
                },
            }
        )
        return

    request = AnswerSubmitRequest(
        match_question_id=match_question_id,
        selected_option_ids=selected_ids,
        client_sent_at=None,
    )
    sm = async_sessionmaker(app.state.engine, expire_on_commit=False)
    try:
        async with sm() as session:
            result = await match_service.submit_answer(
                session,
                runtime,
                match_id=match_id,
                participant_id=conn.participant_id,
                payload=request,
                request_id=message.message_id,
            )
    except AuthError as exc:
        await conn.send(
            {
                "type": "error",
                "message_id": message.message_id,
                "payload": {"code": exc.code, "message": exc.message or ""},
            }
        )
        return

    await conn.send(
        {
            "type": "answer.accepted",
            "message_id": message.message_id,
            "payload": {
                "submission_id": str(result["submission_id"]),
                "accepted": bool(result.get("accepted")),
                "score_awarded": int(result.get("score_awarded", 0)),
                "response_time_ms": int(result.get("response_time_ms", 0)),
            },
        }
    )
