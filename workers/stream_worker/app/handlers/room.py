"""Room-aggregate events: RoomCreated, PlayerJoined, PlayerLeft.

These are diagnostic-only at this phase — we record them in
``events_raw`` so the analytics endpoint can answer "how many joined
before the match started?". No per-type fact table yet.
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
    row = envelope_to_raw_row(env)
    await ch.insert_many(EVENTS_RAW_TABLE, [row], EVENTS_RAW_COLUMNS)
