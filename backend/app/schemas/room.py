"""Room request/response Pydantic models (P05).

Mirrors the BigInt-as-string convention from ``app.schemas.quiz``: every
Snowflake id leaves the API as a JSON string so the JS client never
silently truncates past ``Number.MAX_SAFE_INTEGER``.

Inbound ``quiz_set_id`` accepts either a JSON number or a string —
Pydantic coerces. The wire shape clients see remains string.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.db.models.enums import RoomStatus

# ---------------------------------------------------------------------------
# Create room
# ---------------------------------------------------------------------------


class RoomCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "quiz_set_id": "781234567890123456",
                "max_players": 50,
                "settings": {"scoring_mode": "speed_bonus"},
            }
        }
    )

    quiz_set_id: int
    max_players: int = Field(default=50, ge=2, le=500)
    settings: dict[str, Any] = Field(default_factory=dict)


class RoomCreateResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "room_id": "781234567890123457",
                "code": "DEMO01",
                "status": "lobby",
                "host_ws_url": "/ws/rooms/DEMO01?token=...",
            }
        },
    )

    room_id: int
    code: str
    status: RoomStatus
    host_ws_url: str

    @field_serializer("room_id")
    def _room_id_to_str(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Join room
# ---------------------------------------------------------------------------


class RoomJoinRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"nickname": "Ada", "guest_id": "browser-session-1"}
        }
    )

    nickname: str = Field(min_length=1, max_length=60)
    guest_id: str | None = Field(default=None, max_length=120)


class RoomJoinResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "participant_id": "781234567890123458",
                "room_id": "781234567890123457",
                "code": "DEMO01",
                "nickname": "Ada",
                "participant_token": "eyJhbGciOi...",
                "ws_url": "/ws/rooms/DEMO01?token=...",
            }
        }
    )

    participant_id: int
    room_id: int
    code: str
    nickname: str
    participant_token: str
    ws_url: str

    @field_serializer("participant_id")
    def _pid_to_str(self, value: int) -> str:
        return str(value)

    @field_serializer("room_id")
    def _rid_to_str(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class RoomSnapshotRoom(BaseModel):
    code: str
    status: RoomStatus
    player_count: int


class RoomSnapshotParticipant(BaseModel):
    participant_id: str
    nickname: str
    online: bool


class RoomSnapshotResponse(BaseModel):
    """Payload-block of the WS ``room.snapshot`` message — REST mirror.

    The WS handler in P06 wraps this dict with ``type`` + ``message_id``.
    REST returns the inner payload directly so both surfaces speak the
    same vocabulary.
    """

    room: RoomSnapshotRoom
    participants: list[RoomSnapshotParticipant]
    match: dict[str, Any] | None = None
    leaderboard: list[dict[str, Any]] = Field(default_factory=list)
