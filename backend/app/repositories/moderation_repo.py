"""Moderation report persistence."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ModerationStatus
from app.db.models.moderation_report import ModerationReport


class ModerationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, report: ModerationReport) -> ModerationReport:
        self.session.add(report)
        await self.session.flush()
        return report

    async def get_by_id(self, report_id: int) -> ModerationReport | None:
        return await self.session.get(ModerationReport, report_id)

    async def list_pending(self, *, limit: int = 50) -> list[ModerationReport]:
        stmt = (
            select(ModerationReport)
            .where(ModerationReport.status == ModerationStatus.pending)
            .order_by(ModerationReport.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_status(
        self,
        report: ModerationReport,
        status: ModerationStatus,
        reviewer_id: int,
        reviewed_at: datetime,
    ) -> None:
        report.status = status
        report.reviewed_by = reviewer_id
        report.reviewed_at = reviewed_at
        await self.session.flush()
