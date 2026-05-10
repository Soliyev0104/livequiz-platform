"""`final_scores` table — composite PK (match_id, participant_id)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinalScore(Base):
    __tablename__ = "final_scores"
    __table_args__ = (
        PrimaryKeyConstraint("match_id", "participant_id", name="pk_final_scores"),
    )

    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=False
    )
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("room_participants.id"), nullable=False
    )
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
