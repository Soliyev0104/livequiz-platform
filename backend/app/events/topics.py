"""Redpanda topic constants and event-type → topic routing.

The outbox publisher (P08) loads this map to decide where each row goes.
Defined here so producers (the API) and consumers (stream-worker) read
the same source of truth.
"""

from __future__ import annotations

from typing import Final

from app.events.types import (
    EVT_ANSWER_SUBMITTED,
    EVT_CONTENT_FLAGGED,
    EVT_CONTENT_REPORTED,
    EVT_MATCH_FINISHED,
    EVT_MATCH_STARTED,
    EVT_MODERATION_DECISION,
    EVT_PLAYER_JOINED,
    EVT_PLAYER_LEFT,
    EVT_QUESTION_CLOSED,
    EVT_QUESTION_STARTED,
    EVT_ROOM_CREATED,
)


TOPIC_ROOM: Final = "livequiz.events.room"
TOPIC_MATCH: Final = "livequiz.events.match"
TOPIC_ANSWER: Final = "livequiz.events.answer"
TOPIC_MODERATION: Final = "livequiz.events.moderation"
TOPIC_DEAD_LETTER: Final = "livequiz.events.dead_letter"


_EVENT_TO_TOPIC: dict[str, str] = {
    EVT_ROOM_CREATED: TOPIC_ROOM,
    EVT_PLAYER_JOINED: TOPIC_ROOM,
    EVT_PLAYER_LEFT: TOPIC_ROOM,
    EVT_MATCH_STARTED: TOPIC_MATCH,
    EVT_QUESTION_STARTED: TOPIC_MATCH,
    EVT_QUESTION_CLOSED: TOPIC_MATCH,
    EVT_MATCH_FINISHED: TOPIC_MATCH,
    EVT_ANSWER_SUBMITTED: TOPIC_ANSWER,
    EVT_CONTENT_REPORTED: TOPIC_MODERATION,
    EVT_CONTENT_FLAGGED: TOPIC_MODERATION,
    EVT_MODERATION_DECISION: TOPIC_MODERATION,
}


def topic_for(event_type: str) -> str:
    """Return the Redpanda topic for ``event_type`` or the dead-letter topic."""
    return _EVENT_TO_TOPIC.get(event_type, TOPIC_DEAD_LETTER)
