"""Auth helpers: Argon2id password hashing and HS256 JWT issue/verify.

P03 owns all token logic for the platform — including the participant token
that P05/P06 will consume — so secret/algorithm choice lives in exactly one
place. Tokens are HS256 (single trusted issuer); access and refresh use
**separate secrets** (`JWT_SECRET` vs. `JWT_REFRESH_SECRET`) so a leak of one
does not cascade.

In ``APP_ENV=test`` the Argon2 parameters drop to the cheapest legal values
so the integration suite finishes in seconds. Production parameters use
passlib's defaults for argon2id, which are tuned for ~50ms hash cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from passlib.context import CryptContext
from redis.asyncio import Redis

from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass
class AuthError(Exception):
    """Domain-level auth failure carrying an API error code + HTTP status.

    Translated to the docs/06 error envelope by
    ``app.core.middleware.register_exception_handlers``.
    """

    code: str
    http_status: int
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - debugging convenience
        return f"AuthError({self.code}, {self.http_status}, {self.message})"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def _build_password_hasher() -> CryptContext:
    if get_settings().app_env == "test":
        # Smallest legal argon2 parameters; keeps the test suite fast.
        return CryptContext(
            schemes=["argon2"],
            argon2__memory_cost=8,  # KiB
            argon2__time_cost=1,
            argon2__parallelism=1,
        )
    # Production / local: passlib defaults (argon2id, ~50ms target).
    return CryptContext(schemes=["argon2"], deprecated="auto")


password_hasher: CryptContext = _build_password_hasher()


def hash_password(plain: str) -> str:
    return password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


# Module-level dummy hash used by login() when the email is unknown — gives
# the failing branch the same compute profile as a real verify, so callers
# cannot side-channel-detect "user does not exist". Computed once at import.
_DUMMY_HASH: str = password_hasher.hash("dummy-not-a-real-password")


def dummy_verify(plain: str) -> None:
    """Constant-time-equivalent stand-in for the missing-user branch."""
    try:
        password_hasher.verify(plain, _DUMMY_HASH)
    except (ValueError, TypeError):
        # Expected: the password won't match. Swallow.
        pass


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

ACCESS_TYPE = "access"
REFRESH_TYPE = "refresh"
PARTICIPANT_TYPE = "participant"

_ALG = "HS256"
_PARTICIPANT_TTL_SEC = 4 * 60 * 60  # 4h


def _now_ts() -> int:
    return int(time.time())


def create_access_token(sub: int, role: str, jti: int) -> str:
    settings = get_settings()
    now = _now_ts()
    claims = {
        "sub": str(sub),
        "role": role,
        "jti": str(jti),
        "type": ACCESS_TYPE,
        "iat": now,
        "exp": now + settings.jwt_access_ttl_min * 60,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALG)


def create_refresh_token(sub: int, jti: int) -> str:
    settings = get_settings()
    now = _now_ts()
    claims = {
        "sub": str(sub),
        "jti": str(jti),
        "type": REFRESH_TYPE,
        "iat": now,
        "exp": now + settings.jwt_refresh_ttl_days * 86400,
    }
    return jwt.encode(claims, settings.jwt_refresh_secret, algorithm=_ALG)


def create_participant_token(
    room_code: str, participant_id: int, nickname: str
) -> str:
    """Short-lived token for live-room participants (consumed in P05/P06).

    Signed with ``JWT_SECRET`` — same trust root as access tokens, but the
    ``type`` claim must be checked separately so a participant token cannot
    be substituted for a real user access token.
    """
    settings = get_settings()
    now = _now_ts()
    claims = {
        "type": PARTICIPANT_TYPE,
        "room_code": room_code,
        "participant_id": str(participant_id),
        "nickname": nickname,
        "iat": now,
        "exp": now + _PARTICIPANT_TTL_SEC,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALG)


def decode_token(token: str, expected_type: str, secret: str) -> dict[str, Any]:
    """Decode and validate a token.

    Raises:
      AuthError("AUTH_REQUIRED", 401) — invalid/expired/wrong signature.
      AuthError("FORBIDDEN", 403) — token is well-formed but wrong ``type``.
    """
    try:
        claims: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="invalid token") from exc

    if claims.get("type") != expected_type:
        raise AuthError(
            "FORBIDDEN",
            403,
            message=f"expected token type {expected_type!r}",
        )
    return claims


# ---------------------------------------------------------------------------
# Refresh-jti revocation list (Redis)
# ---------------------------------------------------------------------------


def _revoked_key(jti: str | int) -> str:
    return f"auth:revoked:{jti}"


async def is_jti_revoked(redis: Redis, jti: str | int) -> bool:
    return bool(await redis.exists(_revoked_key(jti)))


async def revoke_jti(redis: Redis, jti: str | int, ttl_seconds: int) -> None:
    """Mark ``jti`` as revoked for ``ttl_seconds``.

    TTL is the remaining lifetime of the token — once it would have expired
    organically there is nothing to defend against, so the key can drop.
    """
    await redis.set(_revoked_key(jti), "1", ex=max(1, int(ttl_seconds)))
