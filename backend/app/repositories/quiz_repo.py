"""Quiz set / question / option / tag persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.answer_option import AnswerOption
from app.db.models.enums import QuizVisibility
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.quiz_tag import QuizTag


class QuizRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, quiz_set_id: int) -> QuizSet | None:
        return await self.session.get(QuizSet, quiz_set_id)

    async def get_by_id_with_questions(self, quiz_set_id: int) -> QuizSet | None:
        stmt = (
            select(QuizSet)
            .where(QuizSet.id == quiz_set_id)
            .options(selectinload(QuizSet.questions).selectinload(Question.options))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_public_published(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[QuizSet]:
        stmt = (
            select(QuizSet)
            .where(
                QuizSet.visibility == QuizVisibility.public,
                QuizSet.is_published.is_(True),
            )
            .order_by(QuizSet.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def search_by_title(self, query: str, *, limit: int = 20) -> list[QuizSet]:
        # Uses ix_quiz_sets_title_trgm (gin_trgm_ops). `%` operator is the
        # trigram similarity match.
        stmt = (
            select(QuizSet)
            .where(QuizSet.title.op("%")(query))
            .order_by(QuizSet.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_tag_by_name(self, name: str) -> QuizTag | None:
        stmt = select(QuizTag).where(QuizTag.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, quiz_set: QuizSet) -> QuizSet:
        self.session.add(quiz_set)
        await self.session.flush()
        return quiz_set

    async def add_tag(self, tag: QuizTag) -> QuizTag:
        self.session.add(tag)
        await self.session.flush()
        return tag

    async def add_question(self, question: Question) -> Question:
        self.session.add(question)
        await self.session.flush()
        return question

    async def add_option(self, option: AnswerOption) -> AnswerOption:
        self.session.add(option)
        await self.session.flush()
        return option
