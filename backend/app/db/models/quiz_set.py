"""`quiz_sets` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import QuizVisibility

if TYPE_CHECKING:
    from app.db.models.question import Question
    from app.db.models.quiz_tag import QuizTag
    from app.db.models.user import User


class QuizSet(Base):
    __tablename__ = "quiz_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[QuizVisibility] = mapped_column(
        Enum(QuizVisibility, name="quiz_visibility", create_type=True),
        nullable=False,
        default=QuizVisibility.private,
    )
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped["User"] = relationship(back_populates="quiz_sets")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz_set",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )
    tags: Mapped[list["QuizTag"]] = relationship(
        secondary="quiz_set_tags",
        back_populates="quiz_sets",
    )
