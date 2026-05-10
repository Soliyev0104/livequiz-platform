"""Persistence query layer.

Each repository takes an `AsyncSession` and never commits — service-layer
code owns transactions so a request can group multiple repo calls into one
atomic unit (and one outbox insert).
"""

from __future__ import annotations

from app.repositories.audit_repo import AuditRepo
from app.repositories.leaderboard_snapshot_repo import LeaderboardSnapshotRepo
from app.repositories.match_repo import MatchRepo
from app.repositories.moderation_repo import ModerationRepo
from app.repositories.outbox_repo import OutboxRepo
from app.repositories.quiz_repo import QuizRepo
from app.repositories.room_repo import RoomRepo
from app.repositories.user_repo import UserRepo

__all__ = [
    "AuditRepo",
    "LeaderboardSnapshotRepo",
    "MatchRepo",
    "ModerationRepo",
    "OutboxRepo",
    "QuizRepo",
    "RoomRepo",
    "UserRepo",
]
