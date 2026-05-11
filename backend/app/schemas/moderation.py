"""Moderation request/response Pydantic models (P09).

Mirrors the BigInt-as-string serialization convention used elsewhere
(``app.schemas.quiz``, ``app.schemas.room``) so Snowflake ids never
truncate on the JS client. Target ids accept either JSON number or
string on the wire and are coerced internally to ``int``.

``ReportCreate`` enforces XOR on the four ``target_*`` / ``room_id``
fields via a model validator: exactly one target must be supplied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.db.models.enums import ModerationStatus


# ---------------------------------------------------------------------------
# Create report
# ---------------------------------------------------------------------------


class ReportCreate(BaseModel):
    """Inbound report body.

    Exactly one of ``target_user_id``, ``target_quiz_set_id``, ``room_id``
    must be set. ``reporter_user_id`` is filled by the router from the
    bearer token (when present) — guests can also report (no token), in
    which case the row carries a ``NULL`` reporter.
    """

    reason: str = Field(min_length=1, max_length=120)
    details: str | None = Field(default=None, max_length=4000)
    target_user_id: int | None = None
    target_quiz_set_id: int | None = None
    room_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "ReportCreate":
        targets = [
            self.target_user_id,
            self.target_quiz_set_id,
            self.room_id,
        ]
        set_count = sum(1 for t in targets if t is not None)
        if set_count == 0:
            raise ValueError(
                "exactly one of target_user_id, target_quiz_set_id, room_id must be set"
            )
        if set_count > 1:
            raise ValueError(
                "target_user_id, target_quiz_set_id, room_id are mutually exclusive"
            )
        return self


class ReportTargetPreview(BaseModel):
    """Light-weight target preview for moderator queue rendering."""

    kind: Literal["user", "quiz_set", "room"]
    id: str
    label: str | None = None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporter_user_id: int | None
    room_id: int | None
    target_user_id: int | None
    target_quiz_set_id: int | None
    reason: str
    details: str | None
    status: ModerationStatus
    created_at: datetime
    reviewed_by: int | None
    reviewed_at: datetime | None

    @field_serializer("id")
    def _id_to_str(self, v: int) -> str:
        return str(v)

    @field_serializer("reporter_user_id")
    def _rep_to_str(self, v: int | None) -> str | None:
        return str(v) if v is not None else None

    @field_serializer("room_id")
    def _room_to_str(self, v: int | None) -> str | None:
        return str(v) if v is not None else None

    @field_serializer("target_user_id")
    def _tuid_to_str(self, v: int | None) -> str | None:
        return str(v) if v is not None else None

    @field_serializer("target_quiz_set_id")
    def _tqs_to_str(self, v: int | None) -> str | None:
        return str(v) if v is not None else None

    @field_serializer("reviewed_by")
    def _rb_to_str(self, v: int | None) -> str | None:
        return str(v) if v is not None else None


class ReportQueueItem(BaseModel):
    """One queue row with an embedded target preview."""

    report: ReportResponse
    target: ReportTargetPreview | None = None


class ReportQueueResponse(BaseModel):
    items: list[ReportQueueItem]
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


DecisionKind = Literal["dismiss", "hide", "mute", "ban"]


class DecisionRequest(BaseModel):
    decision: DecisionKind
    reason: str | None = Field(default=None, max_length=500)


class DecisionResponse(BaseModel):
    report_id: int
    decision: DecisionKind
    status: ModerationStatus

    @field_serializer("report_id")
    def _rid_to_str(self, v: int) -> str:
        return str(v)
