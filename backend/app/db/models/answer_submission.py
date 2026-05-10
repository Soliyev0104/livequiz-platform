"""`answer_submissions` table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnswerSubmission(Base):
    __tablename__ = "answer_submissions"
    __table_args__ = (
        UniqueConstraint(
            "match_question_id", "participant_id", name="ux_submission_once"
        ),
        UniqueConstraint("request_id", name="ux_submission_request"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=False
    )
    match_question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("match_questions.id"), nullable=False
    )
    participant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("room_participants.id"), nullable=False
    )
    selected_option_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False
    )
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    request_id: Mapped[str] = mapped_column(String(80), nullable=False)
