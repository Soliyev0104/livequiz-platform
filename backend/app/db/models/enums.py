"""Domain enums shared by ORM models.

Each enum maps to a Postgres `CREATE TYPE` emitted by the Alembic baseline.
Keep value strings stable — they are persisted in the DB.
"""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    player = "player"
    host = "host"
    moderator = "moderator"
    admin = "admin"


class QuizVisibility(str, enum.Enum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


class RoomStatus(str, enum.Enum):
    lobby = "lobby"
    running = "running"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class QuestionType(str, enum.Enum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    true_false = "true_false"


class ModerationStatus(str, enum.Enum):
    pending = "pending"
    dismissed = "dismissed"
    action_taken = "action_taken"
