"""Admin-only operational endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_role
from app.db.models.enums import RoomStatus, UserRole
from app.db.models.match import Match
from app.db.models.quiz_set import QuizSet
from app.db.models.room import Room
from app.db.models.user import User
from app.schemas.admin import AdminMetricsResponse
from app.schemas.common import ERROR_RESPONSES

router = APIRouter(prefix="/admin", tags=["admin"], responses=ERROR_RESPONSES)


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int((await session.execute(stmt)).scalar_one())


@router.get("/metrics", response_model=AdminMetricsResponse)
async def admin_metrics(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_role(UserRole.admin))],
) -> AdminMetricsResponse:
    return AdminMetricsResponse(
        total_users=await _count(session, select(func.count()).select_from(User)),
        total_quiz_sets=await _count(
            session, select(func.count()).select_from(QuizSet)
        ),
        published_quiz_sets=await _count(
            session,
            select(func.count())
            .select_from(QuizSet)
            .where(QuizSet.is_published.is_(True)),
        ),
        total_rooms=await _count(session, select(func.count()).select_from(Room)),
        total_matches=await _count(session, select(func.count()).select_from(Match)),
        completed_matches=await _count(
            session,
            select(func.count())
            .select_from(Match)
            .where(Match.status == RoomStatus.completed),
        ),
    )
