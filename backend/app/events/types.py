"""Concrete domain event types and aggregate names.

These constants are persisted in ``outbox_events.event_type`` and
``aggregate_type``. They are also the routing key the publisher (P08)
uses to pick a Redpanda topic. Treat the strings as wire format —
renaming any of these is a schema break.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Aggregate types
# ---------------------------------------------------------------------------

AGG_ROOM: Final = "room"
AGG_MATCH: Final = "match"
AGG_ANSWER: Final = "answer"
AGG_MODERATION: Final = "moderation"


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------
# Room lifecycle (P05)
EVT_ROOM_CREATED: Final = "RoomCreated"
EVT_PLAYER_JOINED: Final = "PlayerJoined"
EVT_PLAYER_LEFT: Final = "PlayerLeft"

# Match lifecycle (P07)
EVT_MATCH_STARTED: Final = "MatchStarted"
EVT_QUESTION_STARTED: Final = "QuestionStarted"
EVT_QUESTION_CLOSED: Final = "QuestionClosed"
EVT_MATCH_FINISHED: Final = "MatchFinished"

# Answer (P07)
EVT_ANSWER_SUBMITTED: Final = "AnswerSubmitted"

# Moderation (P09)
EVT_CONTENT_REPORTED: Final = "ContentReported"
EVT_CONTENT_FLAGGED: Final = "ContentFlagged"
EVT_MODERATION_DECISION: Final = "ModerationDecisionMade"


SCHEMA_VERSION: Final = 1
PRODUCER_NAME: Final = "livequiz-api"
