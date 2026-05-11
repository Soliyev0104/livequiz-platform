"""Event-type → Redpanda topic routing for the outbox publisher.

Duplicated from `backend/app/events/topics.py` on purpose: the worker is
its own Python package so it does not import the FastAPI codebase. The
constants are wire-format strings; renaming one is a coordinated schema
break that must happen here AND in the backend module simultaneously.
"""

from __future__ import annotations

from typing import Final


TOPIC_ROOM: Final = "livequiz.events.room"
TOPIC_MATCH: Final = "livequiz.events.match"
TOPIC_ANSWER: Final = "livequiz.events.answer"
TOPIC_MODERATION: Final = "livequiz.events.moderation"
TOPIC_DEAD_LETTER: Final = "livequiz.events.dead_letter"


_EVENT_TO_TOPIC: dict[str, str] = {
    # Room lifecycle
    "RoomCreated": TOPIC_ROOM,
    "PlayerJoined": TOPIC_ROOM,
    "PlayerLeft": TOPIC_ROOM,
    # Match lifecycle
    "MatchStarted": TOPIC_MATCH,
    "QuestionStarted": TOPIC_MATCH,
    "QuestionClosed": TOPIC_MATCH,
    "MatchFinished": TOPIC_MATCH,
    # Answer
    "AnswerSubmitted": TOPIC_ANSWER,
    # Moderation
    "ContentReported": TOPIC_MODERATION,
    "ContentFlagged": TOPIC_MODERATION,
    "ModerationDecisionMade": TOPIC_MODERATION,
}


def topic_for(event_type: str) -> str:
    """Return the Redpanda topic for ``event_type``.

    Unknown event types fall through to the dead-letter topic so the
    publisher does not block the queue on a producer that emitted a
    type the routing table has not learned yet.
    """
    return _EVENT_TO_TOPIC.get(event_type, TOPIC_DEAD_LETTER)
