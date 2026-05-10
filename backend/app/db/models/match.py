"""`matches` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import RoomStatus

if TYPE_CHECKING:
    from app.db.models.match_question import MatchQuestion
    from app.db.models.room import Room


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rooms.id"), nullable=False, unique=True
    )
    quiz_set_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus, name="room_status", create_type=False), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    room: Mapped["Room"] = relationship(back_populates="match")
    questions: Mapped[list["MatchQuestion"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        order_by="MatchQuestion.position",
    )
