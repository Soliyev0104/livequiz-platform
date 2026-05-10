"""Seed one demo room hosted by the host user, using the Networks quiz.

Idempotent on the unique room code `DEMO01`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import get_id_generator
from app.db.models.enums import RoomStatus
from app.db.models.quiz_set import QuizSet
from app.db.models.room import Room
from app.db.models.user import User

DEMO_CODE = "DEMO01"


async def run(session: AsyncSession, host: User, quiz: QuizSet) -> Room:
    existing = (
        await session.execute(select(Room).where(Room.code == DEMO_CODE))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    gen = get_id_generator()
    room = Room(
        id=gen.next_id(),
        code=DEMO_CODE,
        host_id=host.id,
        quiz_set_id=quiz.id,
        status=RoomStatus.lobby,
        max_players=50,
        settings={},
    )
    session.add(room)
    await session.flush()
    return room
