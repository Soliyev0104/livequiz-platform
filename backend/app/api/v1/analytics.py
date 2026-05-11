"""Match analytics endpoint (P08).

``GET /api/v1/matches/{match_id}/analytics``

Two viewer paths, both bearer-token:

* Host (access token, room owner or admin) → full payload.
* Participant (participant token issued at join time, matching the
  room of this match) → limited view: leaderboard + per-question
  accuracy, but no global response-time distribution.

The body is sourced from Redis (warmed by the stream worker on
``MatchFinished``), ClickHouse (live query), or Postgres (honest
fallback). The route always echoes the ``X-Source`` header so a
sustained CH outage is observable.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, get_session
from app.core.config import get_settings
from app.core.security import (
    ACCESS_TYPE,
    PARTICIPANT_TYPE,
    AuthError,
    decode_token,
    is_jti_revoked,
)
from app.db.models.enums import UserRole
from app.db.models.match import Match
from app.db.models.room import Room
from app.repositories.user_repo import UserRepo
from app.services import analytics_service


router = APIRouter(prefix="/matches", tags=["analytics"])


_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Dual-mode auth: access token (host/admin) OR participant token (limited).
# ---------------------------------------------------------------------------


async def _authorize(
    creds: HTTPAuthorizationCredentials | None,
    session: AsyncSession,
    redis: Redis,
    match_id: int,
) -> tuple[str, dict[str, Any]]:
    """Return (mode, claims) where mode is ``host`` or ``participant``.

    The same bearer slot accepts both token types; we try access first
    (most users hitting this URL are hosts), then fall through to the
    participant token. Either failure mode raises ``AUTH_REQUIRED``.
    """
    if creds is None or not creds.credentials:
        raise AuthError("AUTH_REQUIRED", 401, message="missing bearer token")

    settings = get_settings()
    token = creds.credentials

    # Path 1 — access token (host/admin).
    try:
        claims = decode_token(token, ACCESS_TYPE, settings.jwt_secret)
    except AuthError:
        claims = None

    if claims is not None:
        if await is_jti_revoked(redis, claims["jti"]):
            raise AuthError("AUTH_REQUIRED", 401, message="token revoked")
        try:
            user_id = int(claims["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("AUTH_REQUIRED", 401, message="malformed token sub") from exc

        user = await UserRepo(session).get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("AUTH_REQUIRED", 401, message="user not found or inactive")

        # Admins always pass.
        if user.role == UserRole.admin:
            return "host", {"user_id": user_id}

        # Otherwise must own the room of this match.
        match = await session.get(Match, match_id)
        if match is None:
            raise AuthError("ROOM_NOT_FOUND", 404, message="match not found")
        room = await session.get(Room, match.room_id)
        if room is None:
            raise AuthError("ROOM_NOT_FOUND", 404, message="room missing")
        if room.host_id != user_id:
            raise AuthError("FORBIDDEN", 403, message="not the room host")
        return "host", {"user_id": user_id, "room_code": room.code}

    # Path 2 — participant token. Re-raises if invalid.
    pclaims = decode_token(token, PARTICIPANT_TYPE, settings.jwt_secret)
    room_code = str(pclaims["room_code"])
    match = await session.get(Match, match_id)
    if match is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="match not found")
    room = await session.get(Room, match.room_id)
    if room is None or room.code != room_code:
        raise AuthError("FORBIDDEN", 403, message="participant token / match mismatch")
    return "participant", {
        "participant_id": int(pclaims["participant_id"]),
        "room_code": room_code,
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/{match_id}/analytics")
async def get_match_analytics(
    match_id: int,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any]:
    mode, _ = await _authorize(creds, session, redis, match_id)
    result = await analytics_service.get_match_analytics(
        session=session, redis=redis, match_id=match_id
    )
    response.headers["X-Source"] = result.source
    body = result.body

    # Participants get a leaner view — no global percentile distribution
    # and no "most missed" leaderboard. They still see their own match's
    # accuracy + final standings.
    if mode == "participant":
        body = {
            "match_id": body.get("match_id", str(match_id)),
            "final_leaderboard": body.get("final_leaderboard", []),
            "question_accuracy": body.get("question_accuracy", []),
            "total_answers": body.get("total_answers", 0),
        }
    return body
