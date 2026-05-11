"""Rooms router (P05).

Endpoints:
  POST /rooms                    host-only — create lobby from a published quiz
  GET  /rooms/{code}             public — REST mirror of room.snapshot
  POST /rooms/{code}/join        public — admit player/guest, mint participant token

The rooms surface intentionally has no Redis cache layer at the router
level (unlike P04's quiz list). The room snapshot in Redis is the
authoritative live-state view; mutating endpoints write through the
service's ``RoomSnapshotWriter`` so callers don't have to think about
list/detail-cache invalidation.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_redis,
    get_session,
    optional_current_user,
    require_role,
)
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.room import (
    RoomCreate,
    RoomCreateResponse,
    RoomJoinRequest,
    RoomJoinResponse,
    RoomSnapshotResponse,
)
from app.services import room_service

router = APIRouter(prefix="/rooms", tags=["rooms"], responses=ERROR_RESPONSES)


def _admit_sha(request: Request) -> str:
    return request.app.state.capacity_admit_sha


def _release_sha(request: Request) -> str:
    return request.app.state.capacity_release_sha


def _rate_sha(request: Request) -> str:
    return request.app.state.rate_limit_sha


# ---------------------------------------------------------------------------
# Create room
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=RoomCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    payload: RoomCreate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    host: Annotated[User, Depends(require_role(UserRole.host, UserRole.admin))],
) -> RoomCreateResponse:
    room, host_ws_url = await room_service.create_room(
        session,
        redis,
        host=host,
        payload=payload,
        admit_sha=_admit_sha(request),
        release_sha=_release_sha(request),
    )
    return RoomCreateResponse(
        room_id=room.id,
        code=room.code,
        status=room.status,
        host_ws_url=host_ws_url,
    )


# ---------------------------------------------------------------------------
# Get snapshot
# ---------------------------------------------------------------------------


@router.get("/{code}", response_model=RoomSnapshotResponse)
async def get_room(
    code: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> RoomSnapshotResponse:
    snapshot = await room_service.get_snapshot(
        session,
        redis,
        code=code,
        admit_sha=_admit_sha(request),
        release_sha=_release_sha(request),
    )
    return RoomSnapshotResponse(**snapshot)


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


@router.post("/{code}/join", response_model=RoomJoinResponse)
async def join_room(
    code: str,
    payload: RoomJoinRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    user: Annotated[User | None, Depends(optional_current_user)],
) -> RoomJoinResponse:
    ip = request.client.host if request.client else "unknown"
    result = await room_service.join_room(
        session,
        redis,
        code=code,
        payload=payload,
        ip=ip,
        admit_sha=_admit_sha(request),
        release_sha=_release_sha(request),
        rate_limit_sha=_rate_sha(request),
        user=user,
    )
    return RoomJoinResponse(**result)
