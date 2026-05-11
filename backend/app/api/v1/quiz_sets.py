"""Quiz set CRUD + search router (P04).

Routes:
  GET    /quiz-sets                       optional auth — list/search
  POST   /quiz-sets                       host-only — create draft
  GET    /quiz-sets/{id}                  optional auth — owner-or-public
  PATCH  /quiz-sets/{id}                  owner-only — metadata update
  POST   /quiz-sets/{id}/publish          owner-only — validate + publish
  POST   /quiz-sets/{id}/questions        owner-only — add question

The list endpoint caches its JSON response under
``cache:quiz:list:{sha1(filters+viewer)}`` for 60 seconds. Every
write endpoint invalidates the prefix via SCAN+UNLINK so list
freshness lags by at most one round-trip rather than 60 s.

Cache invalidation deliberately lives in the route layer, not in
``quiz_service`` — the service stays Redis-free and unit-testable.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    current_user,
    get_redis,
    get_session,
    optional_current_user,
    require_role,
)
from app.cache.keys import QUIZ_LIST_PREFIX, quiz_list_cache_key
from app.cache.redis import invalidate_prefix
from app.db.models.enums import UserRole
from app.db.models.quiz_set import QuizSet
from app.db.models.user import User
from app.repositories.quiz_repo import QuizRepo
from app.schemas.common import ERROR_RESPONSES
from app.schemas.quiz import (
    QuestionCreate,
    QuestionDetail,
    QuizSetCreate,
    QuizSetDetail,
    QuizSetListResponse,
    QuizSetSummary,
    QuizSetUpdate,
)
from app.services import quiz_service

router = APIRouter(prefix="/quiz-sets", tags=["quiz-sets"], responses=ERROR_RESPONSES)

_LIST_CACHE_TTL_SECONDS = 60


def _summary(quiz: QuizSet, question_count: int) -> QuizSetSummary:
    return QuizSetSummary(
        id=quiz.id,
        title=quiz.title,
        is_published=quiz.is_published,
        version=quiz.version,
        question_count=question_count,
    )


def _detail(
    quiz: QuizSet, *, is_owner_view: bool, question_count: int
) -> QuizSetDetail:
    questions = (
        [
            QuestionDetail.model_validate(q)
            for q in sorted(quiz.questions, key=lambda x: x.position)
        ]
        if is_owner_view
        else None
    )
    return QuizSetDetail(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        visibility=quiz.visibility,
        is_published=quiz.is_published,
        version=quiz.version,
        owner_id=quiz.owner_id,
        tags=sorted(t.name for t in (quiz.tags or [])),
        question_count=question_count,
        created_at=quiz.created_at,
        updated_at=quiz.updated_at,
        questions=questions,
    )


# ---------------------------------------------------------------------------
# List / search
# ---------------------------------------------------------------------------


@router.get("", response_model=QuizSetListResponse)
async def list_quiz_sets(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    viewer: Annotated[User | None, Depends(optional_current_user)],
    q: Annotated[str | None, Query(description="trigram match on title")] = None,
    owner_id: Annotated[int | None, Query(ge=0)] = None,
    tag: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuizSetListResponse:
    cache_key = quiz_list_cache_key(
        viewer_id=viewer.id if viewer else None,
        q=q,
        owner_id=owner_id,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return QuizSetListResponse.model_validate_json(cached)

    rows = await quiz_service.list_quiz_sets(
        session,
        viewer=viewer,
        q=q,
        owner_id=owner_id,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    items = [_summary(quiz, count) for quiz, count in rows]
    body = QuizSetListResponse(items=items, limit=limit, offset=offset)
    await redis.set(cache_key, body.model_dump_json(), ex=_LIST_CACHE_TTL_SECONDS)
    return body


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=QuizSetSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_quiz_set(
    payload: QuizSetCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[
        User, Depends(require_role(UserRole.host, UserRole.admin))
    ],
) -> QuizSetSummary:
    quiz = await quiz_service.create_quiz_set(
        session, owner=owner, payload=payload
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    return _summary(quiz, 0)


# ---------------------------------------------------------------------------
# Read one
# ---------------------------------------------------------------------------


@router.get("/{quiz_set_id}", response_model=QuizSetDetail)
async def get_quiz_set(
    quiz_set_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    viewer: Annotated[User | None, Depends(optional_current_user)],
) -> QuizSetDetail:
    quiz, is_owner_view = await quiz_service.get_quiz_for_viewer(
        session, viewer=viewer, quiz_set_id=quiz_set_id
    )
    return _detail(
        quiz,
        is_owner_view=is_owner_view,
        question_count=len(quiz.questions or []),
    )


# ---------------------------------------------------------------------------
# Update metadata
# ---------------------------------------------------------------------------


@router.patch("/{quiz_set_id}", response_model=QuizSetSummary)
async def patch_quiz_set(
    quiz_set_id: int,
    payload: QuizSetUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[User, Depends(current_user)],
) -> QuizSetSummary:
    quiz = await quiz_service.update_quiz_set(
        session, owner=owner, quiz_set_id=quiz_set_id, payload=payload
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    count = await QuizRepo(session).count_questions(quiz.id)
    return _summary(quiz, count)


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


@router.post("/{quiz_set_id}/publish", response_model=QuizSetSummary)
async def publish_quiz_set(
    quiz_set_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[User, Depends(current_user)],
) -> QuizSetSummary:
    quiz = await quiz_service.publish_quiz_set(
        session, owner=owner, quiz_set_id=quiz_set_id
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    return _summary(quiz, len(quiz.questions or []))


# ---------------------------------------------------------------------------
# Add question
# ---------------------------------------------------------------------------


@router.post(
    "/{quiz_set_id}/questions",
    response_model=QuestionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_question(
    quiz_set_id: int,
    payload: QuestionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[User, Depends(current_user)],
) -> QuestionDetail:
    question = await quiz_service.add_question(
        session, owner=owner, quiz_set_id=quiz_set_id, payload=payload
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    return QuestionDetail.model_validate(question)
