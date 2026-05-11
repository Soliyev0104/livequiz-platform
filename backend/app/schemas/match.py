"""Match request/response Pydantic models (P07).

All Snowflake ids leave the API as JSON strings so JS clients never
truncate past 2^53 — same convention as ``app.schemas.room`` and
``app.schemas.quiz``. Inbound numeric fields accept either int or str
(Pydantic coerces).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# Match start / pause / resume / end
# ---------------------------------------------------------------------------


class MatchStartedResponse(BaseModel):
    match_id: int
    room_code: str
    question_count: int
    status: str

    @field_serializer("match_id")
    def _mid(self, value: int) -> str:
        return str(value)


class MatchControlResponse(BaseModel):
    match_id: int
    status: str

    @field_serializer("match_id")
    def _mid(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Answer submission
# ---------------------------------------------------------------------------


class AnswerSubmitRequest(BaseModel):
    """Player → server payload for ``POST /matches/{id}/answers``.

    ``client_sent_at`` is informational; the server computes
    ``response_time_ms`` from its own ``deadline_at`` − ``submitted_at``.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "match_question_id": "781234567890123459",
                "selected_option_ids": ["781234567890123460"],
                "client_sent_at": "2026-05-11T09:30:00Z",
            }
        },
    )

    match_question_id: int
    selected_option_ids: list[int] = Field(default_factory=list)
    client_sent_at: datetime | None = None


class AnswerSubmitResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "submission_id": "781234567890123461",
                "accepted": True,
                "is_correct": True,
                "score_awarded": 920,
                "response_time_ms": 812,
                "leaderboard_rank": 1,
            }
        }
    )

    submission_id: int
    accepted: bool
    is_correct: bool
    score_awarded: int
    response_time_ms: int
    leaderboard_rank: int | None = None

    @field_serializer("submission_id")
    def _sid(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntryResponse(BaseModel):
    rank: int
    participant_id: str
    nickname: str
    score: int


class LeaderboardResponse(BaseModel):
    match_id: int
    is_final: bool
    entries: list[LeaderboardEntryResponse]

    @field_serializer("match_id")
    def _mid(self, value: int) -> str:
        return str(value)
