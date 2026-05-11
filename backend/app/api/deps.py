"""Common FastAPI dependencies.

P00 wired sessions; P03 adds the auth-shaped deps that the rest of the
platform builds on:

- ``get_session`` / ``get_redis`` — request-scoped clients (unchanged).
- ``current_user`` — decode access token, check revocation, load User.
- ``require_role(*roles)`` — dep factory; 403 unless the user matches.
- ``current_participant`` — used by P06 WS handshake; the participant
  token issuer lives in ``app.core.security`` already.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import (
    ACCESS_TYPE,
    PARTICIPANT_TYPE,
    AuthError,
    decode_token,
    is_jti_revoked,
)
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.repositories.user_repo import UserRepo


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    engine = request.app.state.engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def get_redis(request: Request) -> AsyncIterator[Redis]:
    pool = request.app.state.redis_pool
    async with Redis(connection_pool=pool) as client:
        yield client


# auto_error=False: a missing Authorization header should produce our
# AuthError envelope, not FastAPI's default 403 with a different shape.
_bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> User:
    if creds is None or not creds.credentials:
        raise AuthError("AUTH_REQUIRED", 401, message="missing bearer token")

    settings = get_settings()
    claims = decode_token(creds.credentials, ACCESS_TYPE, settings.jwt_secret)

    if await is_jti_revoked(redis, claims["jti"]):
        raise AuthError("AUTH_REQUIRED", 401, message="token revoked")

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="malformed token sub") from exc

    user = await UserRepo(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthError("AUTH_REQUIRED", 401, message="user not found or inactive")
    return user


async def optional_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> User | None:
    """Return the authenticated user, or ``None`` when no/stale token.

    Used by endpoints whose docs/06 auth column is "Optional" — most
    notably ``GET /quiz-sets`` and ``GET /quiz-sets/{id}``. A missing
    bearer header returns ``None`` (anonymous viewer); an
    invalid/revoked/expired token also returns ``None`` rather than
    401 so a stale browser token cannot lock a user out of public
    pages.
    """
    if creds is None or not creds.credentials:
        return None
    try:
        return await current_user(creds, session, redis)
    except AuthError:
        return None


def require_role(*allowed: UserRole) -> Callable[[User], User]:
    """Build a dependency that allows only users with one of ``allowed``."""
    allowed_set = {r for r in allowed}

    async def _dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed_set:
            raise AuthError(
                "FORBIDDEN",
                403,
                message=f"role '{user.role.value}' not permitted",
            )
        return user

    return _dep


# ---------------------------------------------------------------------------
# Participant token (used by P05 join / P06 WS handshake)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParticipantContext:
    room_code: str
    participant_id: int
    nickname: str


async def current_participant(
    token: Annotated[str, Query(min_length=1, description="participant JWT")],
) -> ParticipantContext:
    settings = get_settings()
    claims = decode_token(token, PARTICIPANT_TYPE, settings.jwt_secret)
    try:
        participant_id = int(claims["participant_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="malformed participant token") from exc
    return ParticipantContext(
        room_code=str(claims["room_code"]),
        participant_id=participant_id,
        nickname=str(claims["nickname"]),
    )


async def current_participant_from_header(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> ParticipantContext:
    """REST equivalent of :func:`current_participant`.

    The participant token rides ``Authorization: Bearer ...`` for REST so
    the player-only endpoints (e.g. ``POST /matches/{id}/answers``) accept
    the same token shape they receive from the WS join flow without
    having to expose it via a query string.
    """
    if creds is None or not creds.credentials:
        raise AuthError("AUTH_REQUIRED", 401, message="missing participant token")
    settings = get_settings()
    claims = decode_token(creds.credentials, PARTICIPANT_TYPE, settings.jwt_secret)
    try:
        participant_id = int(claims["participant_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="malformed participant token") from exc
    return ParticipantContext(
        room_code=str(claims["room_code"]),
        participant_id=participant_id,
        nickname=str(claims["nickname"]),
    )
