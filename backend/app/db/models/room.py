"""`rooms` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import RoomStatus

if TYPE_CHECKING:
    from app.db.models.match import Match
    from app.db.models.room_participant import RoomParticipant
    from app.db.models.user import User


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    host_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    quiz_set_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_sets.id"), nullable=False
    )
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus, name="room_status", create_type=True),
        nullable=False,
        default=RoomStatus.lobby,
    )
    max_players: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    host: Mapped["User"] = relationship(back_populates="hosted_rooms")
    participants: Mapped[list["RoomParticipant"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    match: Mapped["Match | None"] = relationship(
        back_populates="room", uselist=False, cascade="all, delete-orphan"
    )
