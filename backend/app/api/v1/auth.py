"""Auth router: register, login, refresh, logout.

``/me`` lives in ``users.py`` to match the docs/06 endpoint table
(``GET /me``, not ``GET /auth/me``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_redis, get_session
from app.db.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPair,
)
from app.schemas.common import ERROR_RESPONSES
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    return await auth_service.register_user(
        session,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> TokenPair:
    ip = request.client.host if request.client else "unknown"
    rl_sha: str = request.app.state.rate_limit_sha
    _, pair = await auth_service.login(
        session,
        redis,
        email=payload.email,
        password=payload.password,
        ip=ip,
        rate_limit_sha=rl_sha,
    )
    return TokenPair(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> TokenPair:
    _, pair = await auth_service.refresh(
        session, redis, refresh_token=payload.refresh_token
    )
    return TokenPair(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    redis: Annotated[Redis, Depends(get_redis)],
    _user: Annotated[User, Depends(current_user)],
) -> Response:
    """Revoke the refresh token. Caller must hold a valid access token.

    docs/06 marks `/auth/logout` as auth-required, so we depend on
    ``current_user`` even though the revocation target is the refresh jti
    carried in the body.
    """
    await auth_service.logout(redis, refresh_token=payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
