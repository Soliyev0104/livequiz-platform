"""Domain event envelope (per docs/08).

The shape on the wire matches the spec verbatim. This module is the
single place that knows the envelope structure, so the publisher (P08)
and any future consumer can import the same Pydantic model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.events.types import PRODUCER_NAME, SCHEMA_VERSION


class EventEnvelope(BaseModel):
    """JSON envelope wrapping every domain event.

    ``event_id`` and ``aggregate_id`` are Snowflake ``int`` values in
    Postgres but always serialise as JSON strings — JS clients silently
    truncate ints past 2^53.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: int
    event_type: str
    aggregate_type: str
    aggregate_id: int
    occurred_at: datetime
    producer: str = PRODUCER_NAME
    schema_version: int = SCHEMA_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("event_id")
    def _event_id_to_str(self, value: int) -> str:
        return str(value)

    @field_serializer("aggregate_id")
    def _agg_id_to_str(self, value: int) -> str:
        return str(value)

    @field_serializer("occurred_at")
    def _occurred_at_iso(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
