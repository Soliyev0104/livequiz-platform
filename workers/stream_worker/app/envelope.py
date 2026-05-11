"""Envelope validation for the stream worker.

A standalone Pydantic model so the worker has zero dependency on the
FastAPI codebase. Two layers of validation are intentional: each
incoming Kafka message is parsed into an :class:`Envelope` first
(unknown schema_version → straight to DLQ), and only then handed to a
type-specific handler that picks ``payload`` keys it cares about.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


CURRENT_SCHEMA_VERSION = 1


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: int
    event_type: str
    aggregate_type: str
    aggregate_id: int
    occurred_at: datetime
    producer: str
    schema_version: int
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "aggregate_id", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int:
        # Snowflake ids ride as strings on the wire so JS clients don't
        # lose precision; we parse back to ``int`` here for storage.
        if isinstance(value, str):
            return int(value)
        return int(value)


def parse_envelope(raw: bytes) -> Envelope:
    """Parse a Kafka value into an :class:`Envelope`.

    Raises Pydantic's ``ValidationError`` on malformed input — the
    caller routes the offending message to the DLQ topic with the
    original bytes so a human can inspect.
    """
    import json

    return Envelope.model_validate(json.loads(raw))
