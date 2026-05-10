"""Outbox event persistence — read by the publisher worker."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.outbox_event import OutboxEvent


class OutboxRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, event: OutboxEvent) -> OutboxEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def fetch_unpublished(self, *, limit: int = 100) -> list[OutboxEvent]:
        # Hits ix_outbox_unpublished partial index.
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.occurred_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_published(self, event_ids: list[int], published_at: datetime) -> None:
        if not event_ids:
            return
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(event_ids))
            .values(published_at=published_at)
        )
        await self.session.execute(stmt)

    async def increment_attempt(self, event_id: int) -> None:
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(publish_attempts=OutboxEvent.publish_attempts + 1)
        )
        await self.session.execute(stmt)
