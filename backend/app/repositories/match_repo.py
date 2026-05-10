"""Match + match-question + answer-submission persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.answer_submission import AnswerSubmission
from app.db.models.enums import RoomStatus
from app.db.models.match import Match
from app.db.models.match_question import MatchQuestion


class MatchRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, match_id: int) -> Match | None:
        return await self.session.get(Match, match_id)

    async def get_by_room_id(self, room_id: int) -> Match | None:
        stmt = (
            select(Match)
            .where(Match.room_id == room_id)
            .options(selectinload(Match.questions))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, match: Match) -> Match:
        self.session.add(match)
        await self.session.flush()
        return match

    async def add_match_question(self, mq: MatchQuestion) -> MatchQuestion:
        self.session.add(mq)
        await self.session.flush()
        return mq

    async def update_status(self, match: Match, status: RoomStatus) -> None:
        match.status = status
        await self.session.flush()

    async def add_submission(self, submission: AnswerSubmission) -> AnswerSubmission:
        self.session.add(submission)
        await self.session.flush()
        return submission

    async def get_submission_by_request_id(
        self, request_id: str
    ) -> AnswerSubmission | None:
        stmt = select(AnswerSubmission).where(
            AnswerSubmission.request_id == request_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
