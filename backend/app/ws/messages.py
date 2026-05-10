"""Pydantic models for the WebSocket protocol (P06).

Discriminated unions on the ``type`` field. Two top-level adapters:

- :data:`ClientMessageAdapter` parses ``client → server`` envelopes and
  rejects anything not in the known set.
- :data:`ServerMessageAdapter` is a *serialization* helper used by the
  router and tests; building it from a ``dict`` validates that the
  outgoing payload matches the published contract.

Critical schema invariant (see ``docs/07_websocket_protocol.md``):

    ``question.started`` MUST NEVER include ``is_correct`` or
    ``explanation`` on options. The ``QuestionStartedOption`` model
    enumerates exactly the public fields and forbids extras, so a
    future maintainer cannot leak the answer key by passing a richer
    dict through the model.

The ``room.heartbeat.ack`` type is server-only; clients receive it in
response to their own ``room.heartbeat``. ``server_now`` lets the client
estimate clock skew without trusting its local wall clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


# ---------------------------------------------------------------------------
# Client → server
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeartbeatPayload(_StrictModel):
    last_seen_event_id: str | None = None


class HeartbeatMessage(_StrictModel):
    type: Literal["room.heartbeat"]
    message_id: str | None = None
    payload: HeartbeatPayload = Field(default_factory=HeartbeatPayload)


class AnswerSubmitPayload(_StrictModel):
    match_id: str
    match_question_id: str
    selected_option_ids: list[str] = Field(default_factory=list)
    client_sent_at: str | None = None


class AnswerSubmitMessage(_StrictModel):
    type: Literal["answer.submit"]
    message_id: str
    payload: AnswerSubmitPayload


class HostQuestionNextPayload(_StrictModel):
    expected_current_position: int = Field(ge=0)


class HostQuestionNextMessage(_StrictModel):
    type: Literal["host.question.next"]
    message_id: str | None = None
    payload: HostQuestionNextPayload


class HostMatchPausePayload(_StrictModel):
    reason: str | None = Field(default=None, max_length=200)


class HostMatchPauseMessage(_StrictModel):
    type: Literal["host.match.pause"]
    message_id: str | None = None
    payload: HostMatchPausePayload = Field(default_factory=HostMatchPausePayload)


ClientMessage = Annotated[
    HeartbeatMessage
    | AnswerSubmitMessage
    | HostQuestionNextMessage
    | HostMatchPauseMessage,
    Field(discriminator="type"),
]

ClientMessageAdapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


# ---------------------------------------------------------------------------
# Server → client
# ---------------------------------------------------------------------------


class RoomSnapshotRoom(_StrictModel):
    code: str
    status: str
    player_count: int


class RoomSnapshotParticipant(_StrictModel):
    participant_id: str
    nickname: str
    online: bool


class RoomSnapshotPayload(BaseModel):
    """Payload of ``room.snapshot``.

    Allows extra fields (``match`` and ``leaderboard``) to evolve in P07
    without churning this model.
    """

    room: RoomSnapshotRoom
    participants: list[RoomSnapshotParticipant] = Field(default_factory=list)
    match: dict[str, Any] | None = None
    leaderboard: list[dict[str, Any]] = Field(default_factory=list)


class RoomSnapshotMessage(_StrictModel):
    type: Literal["room.snapshot"]
    message_id: str
    payload: RoomSnapshotPayload


class HeartbeatAckPayload(_StrictModel):
    server_now: str
    last_seen_event_id: str | None = None


class HeartbeatAckMessage(_StrictModel):
    type: Literal["room.heartbeat.ack"]
    message_id: str | None = None
    payload: HeartbeatAckPayload


class ParticipantJoinedPayload(_StrictModel):
    participant_id: str
    nickname: str
    player_count: int


class ParticipantJoinedMessage(_StrictModel):
    type: Literal["participant.joined"]
    message_id: str | None = None
    payload: ParticipantJoinedPayload


class ParticipantLeftPayload(_StrictModel):
    participant_id: str
    nickname: str
    player_count: int


class ParticipantLeftMessage(_StrictModel):
    type: Literal["participant.left"]
    message_id: str | None = None
    payload: ParticipantLeftPayload


class MatchStartedPayload(_StrictModel):
    match_id: str
    question_count: int
    server_now: str


class MatchStartedMessage(_StrictModel):
    type: Literal["match.started"]
    message_id: str | None = None
    payload: MatchStartedPayload


class QuestionStartedOption(_StrictModel):
    """Public option as sent in ``question.started``.

    ``extra="forbid"`` is the structural guarantee that no caller can
    sneak ``is_correct`` or ``explanation`` into the wire format. The
    test suite asserts the schema's properties match exactly.
    """

    id: str
    body: str


class QuestionStartedQuestion(_StrictModel):
    body: str
    type: str
    options: list[QuestionStartedOption]


class QuestionStartedPayload(_StrictModel):
    match_question_id: str
    position: int
    question: QuestionStartedQuestion
    started_at: str
    deadline_at: str
    server_now: str


class QuestionStartedMessage(_StrictModel):
    type: Literal["question.started"]
    message_id: str | None = None
    payload: QuestionStartedPayload


class AnswerAcceptedPayload(_StrictModel):
    submission_id: str
    accepted: bool
    score_awarded: int = 0
    response_time_ms: int = 0


class AnswerAcceptedMessage(_StrictModel):
    type: Literal["answer.accepted"]
    message_id: str | None = None
    payload: AnswerAcceptedPayload


class LeaderboardEntry(_StrictModel):
    rank: int
    participant_id: str
    nickname: str
    score: int


class LeaderboardUpdatedPayload(_StrictModel):
    version: int
    top: list[LeaderboardEntry] = Field(default_factory=list)


class LeaderboardUpdatedMessage(_StrictModel):
    type: Literal["leaderboard.updated"]
    message_id: str | None = None
    payload: LeaderboardUpdatedPayload


class QuestionClosedPayload(_StrictModel):
    """Sent ONLY after the question's deadline — safe to reveal answers."""

    match_question_id: str
    correct_option_ids: list[str] = Field(default_factory=list)
    explanation: str | None = None
    accuracy_percent: float | None = None


class QuestionClosedMessage(_StrictModel):
    type: Literal["question.closed"]
    message_id: str | None = None
    payload: QuestionClosedPayload


class MatchFinishedPayload(_StrictModel):
    match_id: str
    final_leaderboard_url: str
    analytics_url: str | None = None


class MatchFinishedMessage(_StrictModel):
    type: Literal["match.finished"]
    message_id: str | None = None
    payload: MatchFinishedPayload


class ErrorPayload(_StrictModel):
    code: str
    message: str | None = None
    retry_after_ms: int | None = None


class ErrorMessage(_StrictModel):
    type: Literal["error"]
    message_id: str | None = None
    payload: ErrorPayload


ServerMessage = Annotated[
    RoomSnapshotMessage
    | HeartbeatAckMessage
    | ParticipantJoinedMessage
    | ParticipantLeftMessage
    | MatchStartedMessage
    | QuestionStartedMessage
    | AnswerAcceptedMessage
    | LeaderboardUpdatedMessage
    | QuestionClosedMessage
    | MatchFinishedMessage
    | ErrorMessage,
    Field(discriminator="type"),
]

ServerMessageAdapter: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def server_now_iso() -> str:
    """ISO-8601 UTC timestamp used for ``server_now`` fields."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
