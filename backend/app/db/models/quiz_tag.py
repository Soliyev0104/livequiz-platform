"""`quiz_tags` table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.quiz_set import QuizSet


class QuizTag(Base):
    __tablename__ = "quiz_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    quiz_sets: Mapped[list["QuizSet"]] = relationship(
        secondary="quiz_set_tags",
        back_populates="tags",
    )
