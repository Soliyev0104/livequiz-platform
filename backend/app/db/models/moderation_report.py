"""`moderation_reports` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import ModerationStatus


class ModerationReport(Base):
    __tablename__ = "moderation_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reporter_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    room_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rooms.id"), nullable=True
    )
    target_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    target_quiz_set_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quiz_sets.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus, name="moderation_status", create_type=True),
        nullable=False,
        default=ModerationStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
