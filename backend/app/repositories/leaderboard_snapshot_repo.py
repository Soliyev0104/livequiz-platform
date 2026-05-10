"""Final-scores (leaderboard snapshot) persistence."""

from __future__ import annotations

from typing import Iterable
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.final_score import FinalScore


class LeaderboardSnapshotRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_upsert(self, rows: Iterable[FinalScore]) -> None:
        """Insert or update final scores keyed by composite PK.

        Uses Postgres `INSERT ... ON CONFLICT DO UPDATE` because P07 may
        recompute final scores on match-finished and we want idempotency.
        """
        payload = [
            {
                "match_id": r.match_id,
                "participant_id": r.participant_id,
                "total_score": r.total_score,
                "correct_count": r.correct_count,
                "average_response_ms": r.average_response_ms,
                "rank": r.rank,
            }
            for r in rows
        ]
        if not payload:
            return
        stmt = insert(FinalScore).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["match_id", "participant_id"],
            set_={
                "total_score": stmt.excluded.total_score,
                "correct_count": stmt.excluded.correct_count,
                "average_response_ms": stmt.excluded.average_response_ms,
                "rank": stmt.excluded.rank,
            },
        )
        await self.session.execute(stmt)

    async def list_by_match_ordered_by_rank(self, match_id: int) -> list[FinalScore]:
        # Hits ix_final_scores_rank.
        stmt = (
            select(FinalScore)
            .where(FinalScore.match_id == match_id)
            .order_by(FinalScore.rank.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
