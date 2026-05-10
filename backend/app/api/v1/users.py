"""User-shaped endpoints: ``/me`` and admin-only ``/users/{id}``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_session, require_role
from app.core.security import AuthError
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.repositories.user_repo import UserRepo
from app.schemas.user import UserPublic

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserPublic)
async def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.get("/users/{user_id}", response_model=UserPublic)
async def get_user(
    user_id: Annotated[int, Path(ge=0)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_role(UserRole.admin))],
) -> User:
    target = await UserRepo(session).get_by_id(user_id)
    if target is None:
        # Not in docs/06's error code table; reuse VALIDATION_ERROR shape via
        # AuthError so envelope stays consistent. 404 status.
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="user not found",
            details={"user_id": user_id},
        )
    return target
