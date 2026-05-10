"""Quiz authoring request/response Pydantic models.

All BigInt ids are serialised as JSON strings (mirroring ``UserPublic``)
so the JS side never silently truncates Snowflake values past
``Number.MAX_SAFE_INTEGER``.

Update vs. create vs. detail responses:

- ``QuizSetSummary`` is the list-row + create-response shape from
  docs/06 (id, title, is_published, version, question_count).
- ``QuizSetDetail`` adds metadata fields and an optional nested
  ``questions`` list — populated only when the requester is the owner.
- ``QuestionUpdate.options`` is ``None`` to mean *leave alone*; a
  list (even an empty one) means *full replace*.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.db.models.enums import QuestionType, QuizVisibility


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


class OptionCreate(BaseModel):
    position: int = Field(ge=1, le=20)
    body: str = Field(min_length=1, max_length=500)
    is_correct: bool = False


class OptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    body: str
    is_correct: bool

    @field_serializer("id")
    def _id_to_str(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


class QuestionCreate(BaseModel):
    position: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1, max_length=2000)
    type: QuestionType
    time_limit_seconds: int = Field(default=20, ge=5, le=120)
    points: int = Field(default=1000, ge=0, le=10_000)
    explanation: str | None = Field(default=None, max_length=2000)
    options: list[OptionCreate] = Field(min_length=2, max_length=10)


class QuestionUpdate(BaseModel):
    position: int | None = Field(default=None, ge=1)
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    type: QuestionType | None = None
    time_limit_seconds: int | None = Field(default=None, ge=5, le=120)
    points: int | None = Field(default=None, ge=0, le=10_000)
    explanation: str | None = Field(default=None, max_length=2000)
    # `None` = leave existing options untouched. A list (even empty) means
    # full replace; the server will refuse if the new shape no longer
    # satisfies validate_publish at publish time, but the draft can be in
    # any state.
    options: list[OptionCreate] | None = None


class QuestionDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    body: str
    type: QuestionType
    time_limit_seconds: int
    points: int
    explanation: str | None
    options: list[OptionResponse]

    @field_serializer("id")
    def _id_to_str(self, value: int) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Quiz sets
# ---------------------------------------------------------------------------


class QuizSetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    visibility: QuizVisibility = QuizVisibility.private
    tags: list[str] = Field(default_factory=list, max_length=20)


class QuizSetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    visibility: QuizVisibility | None = None
    # None = leave alone; list = full replace.
    tags: list[str] | None = None


class QuizSetSummary(BaseModel):
    """Listed-row + create-response shape per docs/06."""

    id: int
    title: str
    is_published: bool
    version: int
    question_count: int

    @field_serializer("id")
    def _id_to_str(self, value: int) -> str:
        return str(value)


class QuizSetDetail(BaseModel):
    id: int
    title: str
    description: str | None
    visibility: QuizVisibility
    is_published: bool
    version: int
    owner_id: int
    tags: list[str]
    question_count: int
    created_at: datetime
    updated_at: datetime
    # Owner view nests questions+options; non-owner public view leaves None.
    questions: list[QuestionDetail] | None = None

    @field_serializer("id")
    def _id_to_str(self, value: int) -> str:
        return str(value)

    @field_serializer("owner_id")
    def _owner_id_to_str(self, value: int) -> str:
        return str(value)


class QuizSetListResponse(BaseModel):
    items: list[QuizSetSummary]
    limit: int
    offset: int
