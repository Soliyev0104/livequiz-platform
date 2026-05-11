"""Moderation events — placeholder ingestion.

A dedicated moderation fact table is on the roadmap; for now we land
the audit row in ``events_raw`` so post-mortem queries (and the
moderator dashboard) can already see the timeline.
"""

from __future__ import annotations

from app.clickhouse_client import ClickHouseClient
from app.envelope import Envelope
from app.handlers._common import (
    EVENTS_RAW_COLUMNS,
    EVENTS_RAW_TABLE,
    envelope_to_raw_row,
)


async def handle(env: Envelope, ch: ClickHouseClient) -> None:
    await ch.insert_many(
        EVENTS_RAW_TABLE, [envelope_to_raw_row(env)], EVENTS_RAW_COLUMNS
    )
