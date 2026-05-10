"""Room lifecycle service (P05): create + join + snapshot.

Responsibilities split across two surfaces:

- ``create_room``: validate the host's quiz, allocate a unique
  6-character Crockford-base32 code, write the row + ``RoomCreated``
  outbox event in a single transaction, then seed Redis (counter +
  initial snapshot).

- ``join_room``: rate-limit by IP, look up the room, admit Lua-atomically
  against ``max_players``, insert the participant in Postgres, write
  ``PlayerJoined`` to the outbox, and rebuild the snapshot. On nickname
  collision (``ux_room_participant_nickname``) the Redis counter is
  decremented as a compensating action so capacity stays accurate.

- ``get_snapshot``: REST mirror of the WS ``room.snapshot`` payload.
  Reads Redis first; on miss, rebuilds from Postgres and writes the
  snapshot back through the single-mutator writer.

Crockford-base32 alphabet ``0123456789ABCDEFGHJKMNPQRSTVWXYZ`` (no
``I, L, O, U``); 6 chars → 32^6 ≈ 1.07e9 codes. The DB-level uniqueness
is the safety net even though collisions at this cardinality are
operationally impossible.
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.cache.rate_limit import acquire as rate_acquire
from app.cache.redis import RoomSnapshotWriter
from app.core.ids import get_id_generator
from app.core.security import AuthError, create_participant_token
from app.db.models.enums import RoomStatus
from app.db.models.outbox_event import OutboxEvent
from app.db.models.room import Room
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User
from app.repositories.outbox_repo import OutboxRepo
from app.repositories.quiz_repo import QuizRepo
from app.repositories.room_repo import RoomRepo
from app.schemas.room import RoomCreate, RoomJoinRequest


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # excludes I, L, O, U
_CODE_LEN = 6
_CODE_RETRIES = 5


def _generate_code() -> str:
    return "".join(secrets.choice(_CROCKFORD_ALPHABET) for _ in range(_CODE_LEN))


# ---------------------------------------------------------------------------
# Rate-limit knobs (10/min per IP+code)
# ---------------------------------------------------------------------------

_JOIN_CAPACITY = 10
_JOIN_REFILL_PER_SEC = 10 / 60  # → 10 tokens fully refill in 60s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _writer(
    redis: Redis,
    *,
    admit_sha: str,
    release_sha: str,
) -> RoomSnapshotWriter:
    return RoomSnapshotWriter(
        redis, admit_sha=admit_sha, release_sha=release_sha
    )


def _participant_payload(p: RoomParticipant) -> dict[str, Any]:
    """Snapshot row for one participant.

    ``online`` defaults to False in P05 — the WS handshake (P06) drives
    presence into ``room:{code}:presence``. Until that ships, all
    participants render as offline in the lobby snapshot, which is
    accurate: nobody is connected via WebSocket yet.
    """
    return {
        "participant_id": str(p.id),
        "nickname": p.nickname,
        "online": False,
    }


async def _build_snapshot(
    session: AsyncSession, room: Room
) -> tuple[dict[str, Any], int]:
    """Rebuild the canonical snapshot dict from Postgres.

    Returns ``(snapshot, active_count)``. ``active_count`` is what the
    Redis capacity counter should equal post-write — used for the
    cold-warmup path to reseed an evicted counter.
    """
    stmt = (
        select(RoomParticipant)
        .where(
            RoomParticipant.room_id == room.id,
            RoomParticipant.left_at.is_(None),
            RoomParticipant.is_kicked.is_(False),
        )
        .order_by(RoomParticipant.joined_at.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    participants = [_participant_payload(p) for p in rows]
    snapshot = {
        "room": {
            "code": room.code,
            "status": room.status.value
            if isinstance(room.status, RoomStatus)
            else str(room.status),
            "player_count": len(rows),
        },
        "participants": participants,
        "match": None,
        "leaderboard": [],
    }
    return snapshot, len(rows)


# ---------------------------------------------------------------------------
# create_room
# ---------------------------------------------------------------------------


async def create_room(
    session: AsyncSession,
    redis: Redis,
    *,
    host: User,
    payload: RoomCreate,
    admit_sha: str,
    release_sha: str,
) -> tuple[Room, str]:
    """Create a room from a published quiz.

    Returns ``(room, host_ws_url)``. Host receives a participant-typed
    JWT so the WS handshake (P06) sees a uniform token shape across
    host and players. ``participant_id`` in the host token references
    ``users.id`` rather than a ``room_participants.id`` row — the host
    is not a player and is not inserted into ``room_participants``;
    P06 will branch on a host-vs-player check at handshake time.
    """
    repo = QuizRepo(session)
    outbox = OutboxRepo(session)
    gen = get_id_generator()

    quiz = await repo.get_by_id(payload.quiz_set_id)
    if quiz is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="quiz set not found",
            details={"quiz_set_id": str(payload.quiz_set_id)},
        )
    if quiz.owner_id != host.id:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not the quiz owner",
            details={"quiz_set_id": str(payload.quiz_set_id)},
        )
    if not quiz.is_published:
        raise AuthError(
            "QUIZ_NOT_PUBLISHED",
            409,
            message="cannot create a room from a draft quiz",
            details={"quiz_set_id": str(payload.quiz_set_id)},
        )

    # Allocate a unique code. Each attempt sits in its own SAVEPOINT so
    # a uniqueness collision rolls back only the failed INSERT, leaving
    # the rest of the request transaction (read of ``quiz``, the
    # eventual outbox INSERT) untouched. Statistically a collision is
    # ~impossible at 32^6 codes, but the safety net here is the
    # ``ux_rooms_code`` unique index, not luck.
    quiz_id = quiz.id  # capture before any potential rollback
    room: Room | None = None
    last_exc: Exception | None = None
    for _ in range(_CODE_RETRIES):
        candidate = _generate_code()
        new_room = Room(
            id=gen.next_id(),
            code=candidate,
            host_id=host.id,
            quiz_set_id=quiz_id,
            status=RoomStatus.lobby,
            max_players=payload.max_players,
            settings=dict(payload.settings or {}),
        )
        try:
            async with session.begin_nested():
                session.add(new_room)
                await session.flush()
        except IntegrityError as exc:
            last_exc = exc
            continue
        room = new_room
        break

    if room is None:
        # Statistically impossible at 32^6; defensive only.
        raise AuthError(
            "INTERNAL_ERROR",
            500,
            message="failed to allocate room code",
            details={"reason": str(last_exc) if last_exc else "unknown"},
        )

    await outbox.add(
        OutboxEvent(
            id=gen.next_id(),
            aggregate_type="room",
            aggregate_id=room.id,
            event_type="RoomCreated",
            payload={
                "room_id": str(room.id),
                "code": room.code,
                "host_id": str(host.id),
                "quiz_set_id": str(quiz.id),
                "max_players": room.max_players,
                "settings": room.settings,
            },
            occurred_at=_utcnow(),
        )
    )

    await session.commit()

    # Seed Redis. Counter and snapshot are both fresh for a brand-new
    # room; if either Redis call fails the next read goes through the
    # cold-warmup branch in get_snapshot, which reseeds them.
    writer = _writer(redis, admit_sha=admit_sha, release_sha=release_sha)
    await writer.participants_count_init(room.code, 0)
    snapshot, _ = await _build_snapshot(session, room)
    await writer.write(room.code, snapshot, status=room.status)

    host_token = create_participant_token(
        room_code=room.code,
        participant_id=host.id,
        nickname=host.display_name,
    )
    host_ws_url = f"/ws/rooms/{room.code}?token={host_token}"
    return room, host_ws_url


# ---------------------------------------------------------------------------
# join_room
# ---------------------------------------------------------------------------


async def join_room(
    session: AsyncSession,
    redis: Redis,
    *,
    code: str,
    payload: RoomJoinRequest,
    ip: str,
    admit_sha: str,
    release_sha: str,
    rate_limit_sha: str,
    user: User | None = None,
) -> dict[str, Any]:
    """Admit a guest or registered player into a lobby room.

    Returns a dict matching ``RoomJoinResponse``. Raises
    ``AuthError`` for the documented 4xx error codes.
    """
    # 1) IP+room rate limit (10/min/(IP, code))
    allowed, _remaining, retry_ms = await rate_acquire(
        redis,
        rate_limit_sha,
        f"rate:join:{ip}:{code}",
        capacity=_JOIN_CAPACITY,
        refill_per_sec=_JOIN_REFILL_PER_SEC,
        cost=1,
    )
    if not allowed:
        raise AuthError(
            "RATE_LIMITED",
            429,
            message="too many join attempts",
            details={"retry_after_ms": retry_ms},
        )

    # 2) Look up room and gate by status
    repo = RoomRepo(session)
    room = await repo.get_by_code(code)
    if room is None:
        raise AuthError(
            "ROOM_NOT_FOUND",
            404,
            message="room code not found",
            details={"code": code},
        )
    if room.status != RoomStatus.lobby:
        raise AuthError(
            "ROOM_NOT_JOINABLE",
            409,
            message="room is not accepting joins",
            details={"code": code, "status": room.status.value},
        )

    # 3) Capacity admission (Redis-first, single round-trip)
    writer = _writer(redis, admit_sha=admit_sha, release_sha=release_sha)
    new_count = await writer.participants_count_admit(code, room.max_players)
    if new_count == -1:
        raise AuthError(
            "ROOM_FULL",
            409,
            message="room is at capacity",
            details={"code": code, "max_players": room.max_players},
        )

    # 4) Insert participant. Postgres' ``ux_room_participant_nickname``
    #    (room_id, lower(nickname)) is the safety net — Redis admission
    #    cannot detect duplicate nicknames.
    gen = get_id_generator()
    participant = RoomParticipant(
        id=gen.next_id(),
        room_id=room.id,
        user_id=user.id if user is not None else None,
        nickname=payload.nickname,
        guest_token_hash=None,  # P05 issues participant-typed JWTs, not bearer tokens
    )
    session.add(participant)
    try:
        await session.flush()
    except IntegrityError:
        # Duplicate nickname raced past us. Compensate the counter so
        # the next legitimate joiner doesn't see a phantom seat taken.
        await session.rollback()
        await writer.participants_count_release(code)
        raise AuthError(
            "DUPLICATE_NICKNAME",
            409,
            message="nickname is already taken in this room",
            details={"code": code, "nickname": payload.nickname},
        )

    # 5) Outbox event in same transaction
    outbox = OutboxRepo(session)
    await outbox.add(
        OutboxEvent(
            id=gen.next_id(),
            aggregate_type="room",
            aggregate_id=room.id,
            event_type="PlayerJoined",
            payload={
                "room_id": str(room.id),
                "participant_id": str(participant.id),
                "nickname": participant.nickname,
                "user_id": str(user.id) if user is not None else None,
            },
            occurred_at=_utcnow(),
        )
    )

    await session.commit()

    # 6) Refresh snapshot from authoritative DB state.
    snapshot, _ = await _build_snapshot(session, room)
    await writer.write(code, snapshot, status=room.status)

    # 7) Mint participant token
    token = create_participant_token(
        room_code=room.code,
        participant_id=participant.id,
        nickname=participant.nickname,
    )

    return {
        "participant_id": participant.id,
        "room_id": room.id,
        "code": room.code,
        "nickname": participant.nickname,
        "participant_token": token,
        "ws_url": f"/ws/rooms/{room.code}?token={token}",
    }


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------


async def build_snapshot(
    session: AsyncSession,
    redis: Redis,
    *,
    code: str,
    admit_sha: str,
    release_sha: str,
) -> dict[str, Any]:
    """Return the canonical ``room.snapshot`` payload for ``code``.

    Used by both the REST mirror (``GET /rooms/{code}``) and the WS
    handshake in P06. Redis-first (the live mutator path keeps it warm);
    on miss the snapshot is rebuilt from Postgres and re-written
    through the single mutator so subsequent reads hit Redis again.

    Match data and the live leaderboard are P07's responsibility — the
    fields exist as ``match: None`` and ``leaderboard: []`` in the lobby
    state so consumers can already structure-match on them.
    """
    writer = _writer(redis, admit_sha=admit_sha, release_sha=release_sha)
    cached = await writer.read(code)
    if cached is not None:
        return cached

    room = await RoomRepo(session).get_by_code(code)
    if room is None:
        raise AuthError(
            "ROOM_NOT_FOUND",
            404,
            message="room code not found",
            details={"code": code},
        )
    snapshot, count = await _build_snapshot(session, room)
    # Reseed counter from authoritative count in case Redis was evicted.
    await writer.participants_count_init(code, count)
    await writer.write(code, snapshot, status=room.status)
    return snapshot


# Back-compat alias for P05 callers (``app.api.v1.rooms``). New code in
# P06+ should use :func:`build_snapshot` directly.
get_snapshot = build_snapshot


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
