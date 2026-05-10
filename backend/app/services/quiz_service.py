"""Quiz authoring service: create / update / publish + question CRUD.

Each public function owns its DB transaction (``session.commit()`` at
the end), mirroring ``auth_service``. Snowflake ids — for quiz sets,
tags, questions, options, and the ``QuizPublished`` outbox row — are
minted via ``app.core.ids.get_id_generator``.

Cache invalidation is the *router*'s responsibility: routes call
``invalidate_prefix(redis, QUIZ_LIST_PREFIX)`` after a service mutation
returns. Keeps the service free of any Redis dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import get_id_generator
from app.core.security import AuthError
from app.db.models.answer_option import AnswerOption
from app.db.models.enums import QuestionType, QuizVisibility
from app.db.models.outbox_event import OutboxEvent
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.user import User
from app.repositories.outbox_repo import OutboxRepo
from app.repositories.quiz_repo import QuizRepo
from app.schemas.quiz import (
    QuestionCreate,
    QuestionUpdate,
    QuizSetCreate,
    QuizSetUpdate,
)
from app.services import moderation_service


# Where the moving row is parked while siblings are renumbered. Sits
# outside the realistic [1, 100] question-position range and below the
# bulk-shift sentinel so the bulk-shift WHERE clauses never touch it.
_PARK_POSITION = QuizRepo._SHIFT_SENTINEL - 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned_quiz(
    repo: QuizRepo, *, owner: User, quiz_set_id: int
) -> QuizSet:
    qs = await repo.get_by_id(quiz_set_id)
    if qs is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="quiz set not found",
            details={"quiz_set_id": quiz_set_id},
        )
    if qs.owner_id != owner.id:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not the quiz owner",
            details={"quiz_set_id": quiz_set_id},
        )
    return qs


async def _resolve_tags(repo: QuizRepo, names: list[str]) -> list[int]:
    """Upsert each tag name; return a de-duplicated list of tag IDs."""
    gen = get_id_generator()
    seen: dict[str, int] = {}
    for raw in names:
        name = raw.strip().lower()
        if not name or name in seen:
            continue
        tag = await repo.upsert_tag(tag_id=gen.next_id(), name=name)
        seen[name] = tag.id
    return list(seen.values())


# ---------------------------------------------------------------------------
# Quiz set lifecycle
# ---------------------------------------------------------------------------


async def create_quiz_set(
    session: AsyncSession, *, owner: User, payload: QuizSetCreate
) -> QuizSet:
    repo = QuizRepo(session)
    gen = get_id_generator()

    quiz = QuizSet(
        id=gen.next_id(),
        owner_id=owner.id,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
        is_published=False,
        version=1,
    )
    await repo.add(quiz)

    if payload.tags:
        tag_ids = await _resolve_tags(repo, payload.tags)
        await repo.replace_quiz_tags(quiz_set_id=quiz.id, tag_ids=tag_ids)

    await session.commit()
    return quiz


async def update_quiz_set(
    session: AsyncSession,
    *,
    owner: User,
    quiz_set_id: int,
    payload: QuizSetUpdate,
) -> QuizSet:
    repo = QuizRepo(session)
    quiz = await _load_owned_quiz(repo, owner=owner, quiz_set_id=quiz_set_id)

    if payload.title is not None:
        quiz.title = payload.title
    if payload.description is not None:
        quiz.description = payload.description
    if payload.visibility is not None:
        quiz.visibility = payload.visibility

    if payload.tags is not None:
        tag_ids = await _resolve_tags(repo, payload.tags)
        await repo.replace_quiz_tags(quiz_set_id=quiz.id, tag_ids=tag_ids)

    quiz.version = quiz.version + 1
    await session.flush()
    await session.commit()
    return quiz


async def get_quiz_for_viewer(
    session: AsyncSession, *, viewer: User | None, quiz_set_id: int
) -> tuple[QuizSet, bool]:
    """Return ``(quiz_set, is_owner_view)``.

    Owner sees questions+options nested. Non-owners see only public
    +published or unlisted+published quizzes; private quizzes raise 403.
    """
    repo = QuizRepo(session)
    quiz = await repo.get_by_id_with_questions(quiz_set_id)
    if quiz is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="quiz set not found",
            details={"quiz_set_id": quiz_set_id},
        )

    is_owner = viewer is not None and quiz.owner_id == viewer.id
    if is_owner:
        return quiz, True

    # Non-owner reads: only published, public or unlisted.
    if not quiz.is_published or quiz.visibility == QuizVisibility.private:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not visible",
            details={"quiz_set_id": quiz_set_id},
        )
    return quiz, False


async def list_quiz_sets(
    session: AsyncSession,
    *,
    viewer: User | None,
    q: str | None,
    owner_id: int | None,
    tag: str | None,
    limit: int,
    offset: int,
) -> list[tuple[QuizSet, int]]:
    repo = QuizRepo(session)
    return await repo.list_for_viewer(
        viewer_id=viewer.id if viewer is not None else None,
        q=q,
        owner_id=owner_id,
        tag=tag,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


async def add_question(
    session: AsyncSession,
    *,
    owner: User,
    quiz_set_id: int,
    payload: QuestionCreate,
) -> Question:
    repo = QuizRepo(session)
    await _load_owned_quiz(repo, owner=owner, quiz_set_id=quiz_set_id)

    gen = get_id_generator()

    if payload.position is None:
        target_position = (await repo.max_question_position(quiz_set_id)) + 1
    else:
        target_position = payload.position
        # Shift siblings if the slot is occupied.
        existing_max = await repo.max_question_position(quiz_set_id)
        if target_position <= existing_max:
            await repo.shift_question_positions(
                quiz_set_id=quiz_set_id,
                from_position=target_position,
                by=1,
            )

    question = Question(
        id=gen.next_id(),
        quiz_set_id=quiz_set_id,
        position=target_position,
        body=payload.body,
        type=payload.type,
        time_limit_seconds=payload.time_limit_seconds,
        points=payload.points,
        explanation=payload.explanation,
    )
    await repo.add_question(question)

    for option_in in payload.options:
        await repo.add_option(
            AnswerOption(
                id=gen.next_id(),
                question_id=question.id,
                position=option_in.position,
                body=option_in.body,
                is_correct=option_in.is_correct,
            )
        )

    # Re-load with options so the response carries them.
    hydrated = await repo.get_question_with_options(question.id)
    assert hydrated is not None  # we just inserted it
    await session.commit()
    return hydrated


async def update_question(
    session: AsyncSession,
    *,
    owner: User,
    question_id: int,
    payload: QuestionUpdate,
) -> Question:
    repo = QuizRepo(session)
    question = await repo.get_question(question_id)
    if question is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="question not found",
            details={"question_id": question_id},
        )

    parent = await repo.get_by_id(question.quiz_set_id)
    if parent is None or parent.owner_id != owner.id:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not the quiz owner",
            details={"question_id": question_id},
        )

    if payload.body is not None:
        question.body = payload.body
    if payload.type is not None:
        question.type = payload.type
    if payload.time_limit_seconds is not None:
        question.time_limit_seconds = payload.time_limit_seconds
    if payload.points is not None:
        question.points = payload.points
    if payload.explanation is not None:
        question.explanation = payload.explanation

    if payload.position is not None and payload.position != question.position:
        await _move_question_to(
            repo,
            quiz_set_id=question.quiz_set_id,
            question=question,
            new_position=payload.position,
        )

    if payload.options is not None:
        gen = get_id_generator()
        new_options = [
            AnswerOption(
                id=gen.next_id(),
                question_id=question.id,
                position=o.position,
                body=o.body,
                is_correct=o.is_correct,
            )
            for o in payload.options
        ]
        await repo.replace_options(
            question_id=question.id, options=new_options
        )

    await session.flush()
    hydrated = await repo.get_question_with_options(question.id)
    assert hydrated is not None
    await session.commit()
    return hydrated


async def _move_question_to(
    repo: QuizRepo,
    *,
    quiz_set_id: int,
    question: Question,
    new_position: int,
) -> None:
    """Move ``question`` to ``new_position`` keeping (quiz_set_id, position) unique.

    Two-phase swap: park the moving row at a sentinel position above the
    safe range, renumber affected siblings, then drop the row at the
    target position.
    """
    if new_position == question.position:
        return

    old_position = question.position
    question.position = _PARK_POSITION
    await repo.session.flush()

    # Two-phase shift to avoid mid-statement violations of the
    # (quiz_set_id, position) unique constraint. Park siblings above the
    # realistic range, then bring them back with the desired delta applied.
    sentinel = QuizRepo._SHIFT_SENTINEL
    if new_position < old_position:
        affected = (
            Question.quiz_set_id == quiz_set_id,
            Question.position >= new_position,
            Question.position < old_position,
            Question.id != question.id,
        )
        delta = 1
    else:
        affected = (
            Question.quiz_set_id == quiz_set_id,
            Question.position > old_position,
            Question.position <= new_position,
            Question.id != question.id,
        )
        delta = -1

    await repo.session.execute(
        update(Question)
        .where(*affected, Question.position < sentinel)
        .values(position=Question.position + sentinel)
    )
    await repo.session.execute(
        update(Question)
        .where(
            Question.quiz_set_id == quiz_set_id,
            Question.position >= sentinel,
            Question.id != question.id,
        )
        .values(position=Question.position - sentinel + delta)
    )

    question.position = new_position
    await repo.session.flush()


async def delete_question(
    session: AsyncSession, *, owner: User, question_id: int
) -> None:
    repo = QuizRepo(session)
    question = await repo.get_question_with_options(question_id)
    if question is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="question not found",
            details={"question_id": question_id},
        )
    parent = await repo.get_by_id(question.quiz_set_id)
    if parent is None or parent.owner_id != owner.id:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not the quiz owner",
            details={"question_id": question_id},
        )

    quiz_set_id = question.quiz_set_id
    deleted_position = question.position

    await repo.delete_question(question)
    await repo.renumber_after_delete(
        quiz_set_id=quiz_set_id, deleted_position=deleted_position
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def validate_publish(quiz_set: QuizSet) -> list[dict[str, str | None]]:
    """Pure validation — returns a list of issue dicts.

    Empty list = ready to publish.
    """
    issues: list[dict[str, str | None]] = []

    if not quiz_set.questions:
        issues.append(
            {
                "question_id": None,
                "code": "EMPTY_QUIZ",
                "message": "Quiz must contain at least one question.",
            }
        )
        return issues

    for q in quiz_set.questions:
        qid_str = str(q.id)
        n_options = len(q.options)
        n_correct = sum(1 for o in q.options if o.is_correct)

        if q.type == QuestionType.single_choice:
            if n_options < 2:
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "INSUFFICIENT_OPTIONS",
                        "message": "single_choice requires at least 2 options.",
                    }
                )
            if n_correct != 1:
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "EXPECTED_ONE_CORRECT",
                        "message": "single_choice requires exactly 1 correct option.",
                    }
                )
        elif q.type == QuestionType.multiple_choice:
            if n_options < 2:
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "INSUFFICIENT_OPTIONS",
                        "message": "multiple_choice requires at least 2 options.",
                    }
                )
            if not (1 <= n_correct < n_options):
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "EXPECTED_SOME_NOT_ALL_CORRECT",
                        "message": (
                            "multiple_choice requires at least 1 correct "
                            "option and not all options correct."
                        ),
                    }
                )
        elif q.type == QuestionType.true_false:
            if n_options != 2:
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "WRONG_TF_OPTION_COUNT",
                        "message": "true_false requires exactly 2 options.",
                    }
                )
            if n_correct != 1:
                issues.append(
                    {
                        "question_id": qid_str,
                        "code": "EXPECTED_ONE_CORRECT",
                        "message": "true_false requires exactly 1 correct option.",
                    }
                )

    return issues


async def publish_quiz_set(
    session: AsyncSession, *, owner: User, quiz_set_id: int
) -> QuizSet:
    repo = QuizRepo(session)
    outbox = OutboxRepo(session)
    gen = get_id_generator()

    quiz = await repo.get_by_id_with_questions(quiz_set_id)
    if quiz is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="quiz set not found",
            details={"quiz_set_id": quiz_set_id},
        )
    if quiz.owner_id != owner.id:
        raise AuthError(
            "FORBIDDEN",
            403,
            message="not the quiz owner",
            details={"quiz_set_id": quiz_set_id},
        )

    # TODO(P09): rule-based moderation runs here. No-op stub today.
    await moderation_service.scan_quiz(quiz)

    issues = validate_publish(quiz)
    if issues:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="quiz set failed publish validation",
            details={"issues": issues},
        )

    quiz.is_published = True
    new_version = quiz.version + 1
    quiz.version = new_version

    occurred_at = datetime.now(timezone.utc)
    await outbox.add(
        OutboxEvent(
            id=gen.next_id(),
            aggregate_type="quiz_set",
            aggregate_id=quiz.id,
            event_type="QuizPublished",
            payload={
                "quiz_set_id": str(quiz.id),
                "version": new_version,
                "owner_id": str(owner.id),
                "title": quiz.title,
            },
            occurred_at=occurred_at,
        )
    )

    await session.commit()
    return quiz
