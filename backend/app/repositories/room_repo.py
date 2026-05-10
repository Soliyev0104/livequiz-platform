"""Room + participant persistence."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.room import Room
from app.db.models.room_participant import RoomParticipant


class RoomRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, room_id: int) -> Room | None:
        return await self.session.get(Room, room_id)

    async def get_by_code(self, code: str) -> Room | None:
        stmt = select(Room).where(Room.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, room: Room) -> Room:
        self.session.add(room)
        await self.session.flush()
        return room

    async def add_participant(self, participant: RoomParticipant) -> RoomParticipant:
        self.session.add(participant)
        await self.session.flush()
        return participant

    async def get_active_participant_count(self, room_id: int) -> int:
        stmt = select(func.count()).where(
            RoomParticipant.room_id == room_id,
            RoomParticipant.left_at.is_(None),
            RoomParticipant.is_kicked.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_participant_by_nickname(
        self, room_id: int, nickname: str
    ) -> RoomParticipant | None:
        # Matches ux_room_participant_nickname: (room_id, lower(nickname)).
        stmt = select(RoomParticipant).where(
            RoomParticipant.room_id == room_id,
            func.lower(RoomParticipant.nickname) == nickname.lower(),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
