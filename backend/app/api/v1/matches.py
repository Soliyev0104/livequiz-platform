"""Match REST surface (P07).

Endpoints:

  POST   /api/v1/rooms/{code}/start          host-only — start match
  POST   /api/v1/rooms/{code}/pause          host-only — pause active question
  POST   /api/v1/rooms/{code}/resume         host-only — resume paused match
  POST   /api/v1/rooms/{code}/end            host-only — finalize match
  POST   /api/v1/matches/{match_id}/answers  participant token — submit answer
  GET    /api/v1/matches/{match_id}/leaderboard  participant token — top N

The host-control endpoints take an access-token (registered user with
``host`` or ``admin`` role); answer submission and leaderboard read take
the participant-token issued at room join. The participant-token path is
``Authorization: Bearer <token>`` to mirror REST conventions and avoid
exposing the token in a query string for non-WS endpoints.

The ``X-Request-ID`` header is REQUIRED on answer submission. The
:class:`RequestIDMiddleware` mints one if absent, but the value the
client sends is what enforces idempotency — so retried submits MUST
echo the same id, not regenerate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ParticipantContext,
    current_participant_from_header,
    get_redis,
    get_session,
    require_role,
)
from app.core.security import AuthError
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.match import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    LeaderboardResponse,
    MatchControlResponse,
    MatchStartedResponse,
)
from app.services import match_service

room_router = APIRouter(prefix="/rooms", tags=["matches"], responses=ERROR_RESPONSES)
match_router = APIRouter(prefix="/matches", tags=["matches"], responses=ERROR_RESPONSES)


def _runtime(request: Request) -> match_service.MatchRuntime:
    runtime = getattr(request.app.state, "match_runtime", None)
    if runtime is None:
        raise RuntimeError("match_runtime not initialized — check app.lifespan")
    return runtime


# ---------------------------------------------------------------------------
# Host control
# ---------------------------------------------------------------------------


@room_router.post(
    "/{code}/start",
    response_model=MatchStartedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_match(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    host: Annotated[User, Depends(require_role(UserRole.host, UserRole.admin))],
) -> MatchStartedResponse:
    from sqlalchemy import func, select

    from app.db.models.match_question import MatchQuestion

    runtime = _runtime(request)
    match = await match_service.start_match(
        session, runtime, host_id=host.id, room_code=code
    )
    count_stmt = select(func.count(MatchQuestion.id)).where(
        MatchQuestion.match_id == match.id
    )
    question_count = int((await session.execute(count_stmt)).scalar_one())
    return MatchStartedResponse(
        match_id=match.id,
        room_code=code,
        question_count=question_count,
        status=match.status.value,
    )


@room_router.post("/{code}/pause", response_model=MatchControlResponse)
async def pause_match(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    host: Annotated[User, Depends(require_role(UserRole.host, UserRole.admin))],
) -> MatchControlResponse:
    runtime = _runtime(request)
    match = await match_service.pause_match(
        session, runtime, host_id=host.id, room_code=code
    )
    return MatchControlResponse(match_id=match.id, status=match.status.value)


@room_router.post("/{code}/resume", response_model=MatchControlResponse)
async def resume_match(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    host: Annotated[User, Depends(require_role(UserRole.host, UserRole.admin))],
) -> MatchControlResponse:
    runtime = _runtime(request)
    match = await match_service.resume_match(
        session, runtime, host_id=host.id, room_code=code
    )
    return MatchControlResponse(match_id=match.id, status=match.status.value)


@room_router.post("/{code}/end", response_model=MatchControlResponse)
async def end_match(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    host: Annotated[User, Depends(require_role(UserRole.host, UserRole.admin))],
) -> MatchControlResponse:
    """Locate the room's match and finalize it.

    The end transaction is owned by the service (it opens its own session
    via the runtime's sessionmaker), so we just resolve room→match here.
    """
    from app.core.security import AuthError
    from app.repositories.match_repo import MatchRepo
    from app.repositories.room_repo import RoomRepo

    room = await RoomRepo(session).get_by_code(code)
    if room is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="room code not found")
    if room.host_id != host.id:
        raise AuthError("FORBIDDEN", 403, message="not the room host")
    match = await MatchRepo(session).get_by_room_id(room.id)
    if match is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="no match for this room")

    runtime = _runtime(request)
    await session.close()
    finished = await match_service.end_match(
        runtime, match_id=match.id, host_id=host.id
    )
    return MatchControlResponse(match_id=finished.id, status=finished.status.value)


# ---------------------------------------------------------------------------
# Participant
# ---------------------------------------------------------------------------


@match_router.post(
    "/{match_id}/answers",
    response_model=AnswerSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_answer(
    match_id: int,
    payload: AnswerSubmitRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    participant: Annotated[
        ParticipantContext, Depends(current_participant_from_header)
    ],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> AnswerSubmitResponse:
    runtime = _runtime(request)
    request_id = x_request_id or getattr(request.state, "request_id", "") or ""
    rate_key = f"rate:answer:{participant.participant_id}:{payload.match_question_id}"
    attempts = await redis.incr(rate_key)
    if attempts == 1:
        await redis.expire(rate_key, 600)
    if attempts > 5:
        ttl_ms = await redis.pttl(rate_key)
        raise AuthError(
            "RATE_LIMITED",
            429,
            message="answer attempts exceeded",
            details={"retry_after_ms": max(0, int(ttl_ms))},
        )
    result = await match_service.submit_answer(
        session,
        runtime,
        match_id=match_id,
        participant_id=participant.participant_id,
        payload=payload,
        request_id=request_id,
    )
    return AnswerSubmitResponse(**result)


@match_router.get(
    "/{match_id}/leaderboard", response_model=LeaderboardResponse
)
async def get_leaderboard(
    match_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    participant: Annotated[
        ParticipantContext, Depends(current_participant_from_header)
    ],
    limit: int = Query(default=10, ge=1, le=100),
) -> LeaderboardResponse:
    runtime = _runtime(request)
    data = await match_service.read_leaderboard(
        session, runtime, match_id=match_id, limit=limit
    )
    return LeaderboardResponse(**data)
