"""AnswerSubmitted handler.

Inserts into both ``events_raw`` (the audit trail) and
``answer_events`` (the fact table the analytics queries hit). Both
inserts share the same buffered client so they batch together — a busy
match produces ~one row per participant per question, which would be
brutally slow at row-at-a-time semantics.
"""

from __future__ import annotations

from app.clickhouse_client import ClickHouseClient
from app.envelope import Envelope
from app.handlers._common import (
    EVENTS_RAW_COLUMNS,
    EVENTS_RAW_TABLE,
    _occurred_at_aware,
    _opt_int,
    envelope_to_raw_row,
)


ANSWER_EVENTS_TABLE = "livequiz.answer_events"
ANSWER_EVENTS_COLUMNS = [
    "event_id",
    "match_id",
    "room_id",
    "participant_id",
    "question_id",
    "is_correct",
    "score_awarded",
    "response_time_ms",
    "occurred_at",
]


async def handle(env: Envelope, ch: ClickHouseClient) -> None:
    payload = env.payload

    match_id = _opt_int(payload.get("match_id"))
    room_id = _opt_int(payload.get("room_id"))
    participant_id = _opt_int(payload.get("participant_id"))
    question_id = _opt_int(payload.get("question_id"))

    # 1. audit row — always emit, even on malformed/partial payloads.
    await ch.insert_many(
        EVENTS_RAW_TABLE, [envelope_to_raw_row(env)], EVENTS_RAW_COLUMNS
    )

    # 2. fact row — requires a fully-qualified set of foreign keys.
    if (
        match_id is None
        or room_id is None
        or participant_id is None
        or question_id is None
    ):
        # Skip the fact insert; ``events_raw`` already has the
        # original envelope for after-the-fact recovery.
        return

    is_correct = 1 if bool(payload.get("is_correct")) else 0
    try:
        score_awarded = int(payload.get("score_awarded", 0))
    except (TypeError, ValueError):
        score_awarded = 0
    try:
        response_time_ms = max(0, int(payload.get("response_time_ms", 0)))
    except (TypeError, ValueError):
        response_time_ms = 0

    row = [
        env.event_id,
        match_id,
        room_id,
        participant_id,
        question_id,
        is_correct,
        score_awarded,
        response_time_ms,
        _occurred_at_aware(env),
    ]
    await ch.insert_many(ANSWER_EVENTS_TABLE, [row], ANSWER_EVENTS_COLUMNS)
