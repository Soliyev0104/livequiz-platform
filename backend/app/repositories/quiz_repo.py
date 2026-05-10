"""Quiz set / question / option / tag persistence."""

from __future__ import annotations

from sqlalchemy import (
    and_,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.answer_option import AnswerOption
from app.db.models.enums import QuizVisibility
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.quiz_set_tag import QuizSetTag
from app.db.models.quiz_tag import QuizTag


class QuizRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- quiz sets --------------------------------------------------------

    async def get_by_id(self, quiz_set_id: int) -> QuizSet | None:
        return await self.session.get(QuizSet, quiz_set_id)

    async def get_by_id_with_questions(self, quiz_set_id: int) -> QuizSet | None:
        stmt = (
            select(QuizSet)
            .where(QuizSet.id == quiz_set_id)
            .options(
                selectinload(QuizSet.questions).selectinload(Question.options),
                selectinload(QuizSet.tags),
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_tags(self, quiz_set_id: int) -> QuizSet | None:
        stmt = (
            select(QuizSet)
            .where(QuizSet.id == quiz_set_id)
            .options(selectinload(QuizSet.tags))
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
        sim = func.similarity(QuizSet.title, query)
        stmt = (
            select(QuizSet)
            .where(QuizSet.title.op("%")(query))
            .order_by(sim.desc(), QuizSet.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_viewer(
        self,
        *,
        viewer_id: int | None,
        q: str | None = None,
        owner_id: int | None = None,
        tag: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[QuizSet, int]]:
        """Return (quiz_set, question_count) rows visible to ``viewer_id``.

        Visibility:
          - Public + published rows are always visible.
          - The viewer's own quizzes (any visibility, draft or published)
            are visible when authenticated.
        Optional filters: ``q`` (trigram match on title), ``owner_id``,
        ``tag`` (existence join).
        """
        question_count = (
            select(func.count(Question.id))
            .where(Question.quiz_set_id == QuizSet.id)
            .correlate(QuizSet)
            .scalar_subquery()
            .label("question_count")
        )

        public_branch = and_(
            QuizSet.visibility == QuizVisibility.public,
            QuizSet.is_published.is_(True),
        )
        own_branch = (
            QuizSet.owner_id == viewer_id if viewer_id is not None else literal(False)
        )
        visibility_clause = or_(public_branch, own_branch)

        stmt = select(QuizSet, question_count).where(visibility_clause)

        if q:
            stmt = stmt.where(QuizSet.title.op("%")(q))
            sim = func.similarity(QuizSet.title, q)
            stmt = stmt.order_by(sim.desc(), QuizSet.created_at.desc())
        else:
            stmt = stmt.order_by(QuizSet.created_at.desc())

        if owner_id is not None:
            stmt = stmt.where(QuizSet.owner_id == owner_id)

        if tag:
            tag_exists = (
                select(literal(1))
                .select_from(QuizSetTag)
                .join(QuizTag, QuizTag.id == QuizSetTag.tag_id)
                .where(
                    QuizSetTag.quiz_set_id == QuizSet.id,
                    QuizTag.name == tag,
                )
            )
            stmt = stmt.where(exists(tag_exists))

        stmt = stmt.limit(limit).offset(offset)

        rows = (await self.session.execute(stmt)).all()
        return [(row[0], int(row[1] or 0)) for row in rows]

    async def add(self, quiz_set: QuizSet) -> QuizSet:
        self.session.add(quiz_set)
        await self.session.flush()
        return quiz_set

    async def is_owner(self, quiz_set_id: int, user_id: int) -> bool:
        stmt = select(literal(1)).where(
            QuizSet.id == quiz_set_id, QuizSet.owner_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def count_questions(self, quiz_set_id: int) -> int:
        stmt = select(func.count(Question.id)).where(
            Question.quiz_set_id == quiz_set_id
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # -- tags -------------------------------------------------------------

    async def get_tag_by_name(self, name: str) -> QuizTag | None:
        stmt = select(QuizTag).where(QuizTag.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_tag(self, tag: QuizTag) -> QuizTag:
        self.session.add(tag)
        await self.session.flush()
        return tag

    async def upsert_tag(self, *, tag_id: int, name: str) -> QuizTag:
        """INSERT … ON CONFLICT (name) DO NOTHING; SELECT on miss.

        ``tag_id`` is a freshly-minted Snowflake from the caller. If the
        tag already exists the ID is discarded; otherwise it is the new
        row's PK. The function always returns a hydrated ORM row.
        """
        stmt = (
            pg_insert(QuizTag)
            .values(id=tag_id, name=name)
            .on_conflict_do_nothing(index_elements=["name"])
            .returning(QuizTag.id)
        )
        new_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if new_id is None:
            existing = (
                await self.session.execute(
                    select(QuizTag).where(QuizTag.name == name)
                )
            ).scalar_one()
            return existing
        # Inserted: hydrate by id.
        await self.session.flush()
        return await self.session.get(QuizTag, new_id)  # type: ignore[return-value]

    async def replace_quiz_tags(
        self, *, quiz_set_id: int, tag_ids: list[int]
    ) -> None:
        await self.session.execute(
            delete(QuizSetTag).where(QuizSetTag.quiz_set_id == quiz_set_id)
        )
        for tag_id in tag_ids:
            self.session.add(QuizSetTag(quiz_set_id=quiz_set_id, tag_id=tag_id))
        await self.session.flush()

    # -- questions / options ---------------------------------------------

    async def add_question(self, question: Question) -> Question:
        self.session.add(question)
        await self.session.flush()
        return question

    async def add_option(self, option: AnswerOption) -> AnswerOption:
        self.session.add(option)
        await self.session.flush()
        return option

    async def get_question(self, question_id: int) -> Question | None:
        return await self.session.get(Question, question_id)

    async def get_question_with_options(
        self, question_id: int
    ) -> Question | None:
        stmt = (
            select(Question)
            .where(Question.id == question_id)
            .options(selectinload(Question.options))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def max_question_position(self, quiz_set_id: int) -> int:
        stmt = select(func.coalesce(func.max(Question.position), 0)).where(
            Question.quiz_set_id == quiz_set_id
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ``ux_questions_quiz_position`` is a non-deferrable unique constraint,
    # so Postgres can fire mid-statement on a set-based UPDATE that would
    # transiently produce duplicates (e.g. shifting positions 2,3 to 3,4).
    # Two-phase via a sentinel offset sidesteps that — every affected row
    # is parked above the realistic position range first, then brought
    # back with the desired shift.
    _SHIFT_SENTINEL = 1_000_000

    async def shift_question_positions(
        self, *, quiz_set_id: int, from_position: int, by: int = 1
    ) -> None:
        """Shift every sibling at or after ``from_position`` by ``by``."""
        sentinel = self._SHIFT_SENTINEL
        await self.session.execute(
            update(Question)
            .where(
                Question.quiz_set_id == quiz_set_id,
                Question.position >= from_position,
                Question.position < sentinel,
            )
            .values(position=Question.position + sentinel)
        )
        await self.session.execute(
            update(Question)
            .where(
                Question.quiz_set_id == quiz_set_id,
                Question.position >= sentinel,
            )
            .values(position=Question.position - sentinel + by)
        )

    async def renumber_after_delete(
        self, *, quiz_set_id: int, deleted_position: int
    ) -> None:
        sentinel = self._SHIFT_SENTINEL
        await self.session.execute(
            update(Question)
            .where(
                Question.quiz_set_id == quiz_set_id,
                Question.position > deleted_position,
                Question.position < sentinel,
            )
            .values(position=Question.position + sentinel)
        )
        await self.session.execute(
            update(Question)
            .where(
                Question.quiz_set_id == quiz_set_id,
                Question.position >= sentinel,
            )
            .values(position=Question.position - sentinel - 1)
        )

    async def delete_question(self, question: Question) -> None:
        # Go through the ORM so the ``cascade="all, delete-orphan"`` on
        # ``Question.options`` removes the answer_options rows in the
        # same flush. Core ``DELETE`` would skip that and trip the FK.
        await self.session.delete(question)
        await self.session.flush()

    async def replace_options(
        self, *, question_id: int, options: list[AnswerOption]
    ) -> None:
        await self.session.execute(
            delete(AnswerOption).where(AnswerOption.question_id == question_id)
        )
        for opt in options:
            self.session.add(opt)
        await self.session.flush()
