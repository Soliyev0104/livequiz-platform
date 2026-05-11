"""Shared helpers across event handlers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.envelope import Envelope


EVENTS_RAW_TABLE = "livequiz.events_raw"
EVENTS_RAW_COLUMNS = [
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "room_id",
    "match_id",
    "participant_id",
    "question_id",
    "occurred_at",
    "payload",
]


def _opt_int(value: Any) -> int | None:
    """Coerce a JSON-ish snowflake to ``int`` or ``None``.

    The wire format ships ids as strings; some legacy payloads may
    omit a field or send ``null``.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _occurred_at_aware(env: Envelope) -> datetime:
    if env.occurred_at.tzinfo is None:
        return env.occurred_at.replace(tzinfo=timezone.utc)
    return env.occurred_at.astimezone(timezone.utc)


def envelope_to_raw_row(env: Envelope) -> list[Any]:
    """Build the ``events_raw`` row tuple matching ``EVENTS_RAW_COLUMNS``.

    ``payload`` is stored as a JSON-text column so future schema
    additions don't break the ingest path — analytics queries can pull
    the field with ``JSONExtract*`` and we keep the audit fidelity of
    "every byte that was on the wire".
    """
    payload = env.payload
    return [
        env.event_id,
        env.event_type,
        env.aggregate_type,
        env.aggregate_id,
        _opt_int(payload.get("room_id")),
        _opt_int(payload.get("match_id")),
        _opt_int(payload.get("participant_id")),
        _opt_int(payload.get("question_id")),
        _occurred_at_aware(env),
        json.dumps(payload, separators=(",", ":")),
    ]
