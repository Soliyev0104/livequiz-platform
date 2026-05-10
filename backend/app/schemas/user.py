"""User-shaped Pydantic models.

Snowflake ids are 64-bit ints; we serialise them as JSON strings so the
JS-side ``Number.MAX_SAFE_INTEGER`` (2^53 - 1) ceiling never silently
truncates them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, field_serializer

from app.db.models.enums import UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    role: UserRole

    @field_serializer("id")
    def _id_to_str(self, value: int) -> str:
        return str(value)
