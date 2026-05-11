"""Auth request/response Pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._email import LooseEmailStr
from app.schemas.user import UserPublic


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "host@example.com",
                "password": "StrongPass123!",
                "display_name": "Demo Host",
            }
        }
    )

    email: LooseEmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


# Login does NOT enforce min_length=8 — the seeded demo users use shorter
# passwords (host, admin, player) and must be able to authenticate. ``email``
# uses LooseEmailStr (not pydantic's EmailStr): the seeded accounts live on the
# reserved ``.local`` TLD, which email-validator rejects; and login matches
# against stored credentials, so RFC-strict validation is unnecessary here.
class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "host@livequiz.local", "password": "host"}
        }
    )

    email: LooseEmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOi...",
                "refresh_token": "eyJhbGciOi...",
                "token_type": "bearer",
                "expires_in": 900,
            }
        }
    )

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # access-token lifetime in seconds


# RegisterResponse is structurally identical to UserPublic; alias rather than
# duplicate fields so any future change to UserPublic flows through.
RegisterResponse = UserPublic
