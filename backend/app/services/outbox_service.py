"""Transactional outbox helper.

Every business write that needs to publish a domain event calls
:func:`register_event` inside the same SQLAlchemy transaction that
performs the durable write. The publisher worker (P08) later picks the
row up and pushes it to Redpanda; the API never touches the broker
directly, so a broker outage cannot fail or delay a gameplay write.

The helper only allocates a Snowflake id and inserts the row — it does
not flush. The caller's outer ``commit()`` is the boundary; if the
business write rolls back, the outbox row rolls back with it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import get_id_generator
from app.db.models.outbox_event import OutboxEvent
from app.events.envelope import utcnow


async def register_event(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    """Insert one outbox row in the caller's transaction.

    Returns the hydrated :class:`OutboxEvent` so the caller can log or
    surface the ``event_id``. The row is added via ``session.add`` and
    flushed so foreign-key relationships and the unique-id constraint
    are validated synchronously; commit is the caller's responsibility.
    """
    gen = get_id_generator()
    row = OutboxEvent(
        id=gen.next_id(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(row)
    await session.flush()
    return row
