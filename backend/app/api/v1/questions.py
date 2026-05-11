"""Question-level endpoints (PATCH/DELETE).

The create-question route lives on the quiz_sets router so it can be
nested under ``/quiz-sets/{id}/questions``; PATCH and DELETE address
the question by its own id, so they live here under ``/questions``.

Both routes invalidate the ``cache:quiz:list:*`` prefix on success
because list-row metadata (e.g. ``question_count``) changes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_redis, get_session
from app.cache.keys import QUIZ_LIST_PREFIX
from app.cache.redis import invalidate_prefix
from app.db.models.user import User
from app.schemas.common import ERROR_RESPONSES
from app.schemas.quiz import QuestionDetail, QuestionUpdate
from app.services import quiz_service

router = APIRouter(prefix="/questions", tags=["questions"], responses=ERROR_RESPONSES)


@router.patch("/{question_id}", response_model=QuestionDetail)
async def patch_question(
    question_id: int,
    payload: QuestionUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[User, Depends(current_user)],
) -> QuestionDetail:
    question = await quiz_service.update_question(
        session, owner=owner, question_id=question_id, payload=payload
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    return QuestionDetail.model_validate(question)


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    owner: Annotated[User, Depends(current_user)],
) -> Response:
    await quiz_service.delete_question(
        session, owner=owner, question_id=question_id
    )
    await invalidate_prefix(redis, QUIZ_LIST_PREFIX)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
