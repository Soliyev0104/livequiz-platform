"""ORM models — re-exported so `Base.metadata` sees every table.

Importing this package registers all 15 mapped classes against the shared
`Base.metadata`, which Alembic's `target_metadata` consults.
"""

from __future__ import annotations

from app.db.models.answer_option import AnswerOption
from app.db.models.answer_submission import AnswerSubmission
from app.db.models.audit_log import AuditLog
from app.db.models.enums import (
    ModerationStatus,
    QuestionType,
    QuizVisibility,
    RoomStatus,
    UserRole,
)
from app.db.models.final_score import FinalScore
from app.db.models.match import Match
from app.db.models.match_question import MatchQuestion
from app.db.models.moderation_report import ModerationReport
from app.db.models.outbox_event import OutboxEvent
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.quiz_set_tag import QuizSetTag
from app.db.models.quiz_tag import QuizTag
from app.db.models.room import Room
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User

__all__ = [
    "AnswerOption",
    "AnswerSubmission",
    "AuditLog",
    "FinalScore",
    "Match",
    "MatchQuestion",
    "ModerationReport",
    "ModerationStatus",
    "OutboxEvent",
    "Question",
    "QuestionType",
    "QuizSet",
    "QuizSetTag",
    "QuizTag",
    "QuizVisibility",
    "Room",
    "RoomParticipant",
    "RoomStatus",
    "User",
    "UserRole",
]
