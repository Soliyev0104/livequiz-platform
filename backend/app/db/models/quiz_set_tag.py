"""`quiz_set_tags` association table (composite PK)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuizSetTag(Base):
    __tablename__ = "quiz_set_tags"
    __table_args__ = (
        PrimaryKeyConstraint("quiz_set_id", "tag_id", name="pk_quiz_set_tags"),
    )

    quiz_set_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_sets.id"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quiz_tags.id"), nullable=False
    )
