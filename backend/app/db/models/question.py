"""`questions` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import QuestionType

if TYPE_CHECKING:
    from app.db.models.answer_option import AnswerOption
    from app.db.models.quiz_set import QuizSet


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("quiz_set_id", "position", name="ux_questions_quiz_position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quiz_set_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_sets.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, name="question_type", create_type=True), nullable=False
    )
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    quiz_set: Mapped["QuizSet"] = relationship(back_populates="questions")
    options: Mapped[list["AnswerOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="AnswerOption.position",
    )
