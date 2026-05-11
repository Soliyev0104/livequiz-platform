"""Moderation router (P09).

Endpoints:

  POST /reports                                       optional auth
  GET  /moderation/reports?status=&limit=&offset=     moderator+admin
  POST /moderation/reports/{id}/decision              moderator+admin

``POST /reports`` accepts both authenticated user tokens and anonymous
guest submissions. When a bearer token is present and decodes as a
valid access token, its subject becomes the ``reporter_user_id`` on the
report row; otherwise the row carries ``NULL``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_redis,
    get_session,
    optional_current_user,
    require_role,
)
from app.db.models.enums import ModerationStatus, UserRole
from app.db.models.user import User
from app.repositories.moderation_repo import ModerationRepo
from app.schemas.moderation import (
    DecisionRequest,
    DecisionResponse,
    ReportCreate,
    ReportQueueItem,
    ReportQueueResponse,
    ReportResponse,
    ReportTargetPreview,
)
from app.services import moderation_service

router = APIRouter(tags=["moderation"])


# ---------------------------------------------------------------------------
# POST /reports
# ---------------------------------------------------------------------------


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_endpoint(
    payload: ReportCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    reporter: Annotated[User | None, Depends(optional_current_user)],
) -> ReportResponse:
    report = await moderation_service.create_report(
        session,
        reporter_user_id=reporter.id if reporter is not None else None,
        room_id=payload.room_id,
        target_user_id=payload.target_user_id,
        target_quiz_set_id=payload.target_quiz_set_id,
        reason=payload.reason,
        details=payload.details,
    )
    return ReportResponse.model_validate(report)


# ---------------------------------------------------------------------------
# GET /moderation/reports
# ---------------------------------------------------------------------------


@router.get("/moderation/reports", response_model=ReportQueueResponse)
async def list_reports(
    session: Annotated[AsyncSession, Depends(get_session)],
    _mod: Annotated[
        User, Depends(require_role(UserRole.moderator, UserRole.admin))
    ],
    status_: ModerationStatus | None = Query(default=ModerationStatus.pending, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReportQueueResponse:
    repo = ModerationRepo(session)
    rows = await repo.list_by_status(status_, limit=limit, offset=offset)
    items: list[ReportQueueItem] = []
    for r in rows:
        preview_dict = await moderation_service.build_target_preview(session, r)
        preview = (
            ReportTargetPreview.model_validate(preview_dict)
            if preview_dict is not None
            else None
        )
        items.append(
            ReportQueueItem(
                report=ReportResponse.model_validate(r),
                target=preview,
            )
        )
    return ReportQueueResponse(items=items, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# POST /moderation/reports/{id}/decision
# ---------------------------------------------------------------------------


@router.post(
    "/moderation/reports/{report_id}/decision",
    response_model=DecisionResponse,
)
async def decide_report(
    report_id: int,
    payload: DecisionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    moderator: Annotated[
        User, Depends(require_role(UserRole.moderator, UserRole.admin))
    ],
) -> DecisionResponse:
    report = await moderation_service.decide(
        session,
        redis,
        moderator=moderator,
        report_id=report_id,
        decision=payload.decision,
        reason=payload.reason,
    )
    return DecisionResponse(
        report_id=report.id,
        decision=payload.decision,
        status=report.status,
    )
