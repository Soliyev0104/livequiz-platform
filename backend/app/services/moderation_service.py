"""Moderation service — fully fleshed out in P09.

P04 only needs a stable call site so ``quiz_service.publish_quiz_set``
can invoke a moderation hook today and have P09 fill in the rule-based
scanner without touching publish-flow code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.quiz_set import QuizSet


async def scan_quiz(quiz_set: "QuizSet") -> None:
    """No-op until P09 wires content moderation rules.

    Returning ``None`` means "no issues raised". When P09 lands, this
    will inspect ``quiz_set.title``, ``quiz_set.description``, and each
    question/option body, then either return cleanly or raise a
    domain-level moderation error.
    """
    return None
