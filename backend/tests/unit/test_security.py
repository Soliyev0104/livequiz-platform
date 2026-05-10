"""Unit tests for app.core.security.

No DB or Redis container is spun up. The revocation test uses a tiny
in-process fake that only implements the two methods we touch
(``set`` with ex=, ``exists``). Real Redis is exercised end-to-end in
``tests/integration/test_auth_flow.py``.
"""

from __future__ import annotations

import os
import time

# Tests run with APP_ENV=test (set by integration conftest); units must
# also boot in test mode so Argon2 stays cheap.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SNOWFLAKE_WORKER_ID", "9")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "unit-access-secret")
os.environ.setdefault("JWT_REFRESH_SECRET", "unit-refresh-secret")

import jwt  # noqa: E402
import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import (  # noqa: E402
    ACCESS_TYPE,
    PARTICIPANT_TYPE,
    REFRESH_TYPE,
    AuthError,
    create_access_token,
    create_participant_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_jti_revoked,
    revoke_jti,
    verify_password,
)


class _FakeRedis:
    """Minimal stand-in for redis.asyncio.Redis.

    Only implements the two methods ``is_jti_revoked``/``revoke_jti`` use.
    Tracks expiry just enough to verify the TTL flag was passed in.
    """

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = (value, ex)
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_password_hash_roundtrip() -> None:
    h = hash_password("hunter2!!")
    assert h != "hunter2!!"
    assert verify_password("hunter2!!", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_handles_garbage_hash() -> None:
    # A non-argon2 hash string must not raise; verify returns False.
    assert verify_password("anything", "not-a-real-hash") is False


def test_dummy_verify_branch_runs_in_similar_time_envelope() -> None:
    """The missing-user branch should pay roughly the same compute as the
    real branch, so an attacker can't side-channel-detect non-existing users.

    We don't assert ns-level parity (Argon2 is randomised); we just require
    both branches to land in the same order of magnitude.
    """
    h = hash_password("real-pw")

    t0 = time.perf_counter()
    verify_password("real-pw", h)
    real_dt = time.perf_counter() - t0

    from app.core.security import dummy_verify

    t0 = time.perf_counter()
    dummy_verify("real-pw")
    dummy_dt = time.perf_counter() - t0

    # Within 5x — sanity check, not a statistical guarantee.
    assert real_dt < dummy_dt * 5
    assert dummy_dt < real_dt * 5


# ---------------------------------------------------------------------------
# JWT round-trip
# ---------------------------------------------------------------------------


def test_access_token_roundtrip() -> None:
    settings = get_settings()
    token = create_access_token(sub=42, role="player", jti=12345)
    claims = decode_token(token, ACCESS_TYPE, settings.jwt_secret)
    assert claims["sub"] == "42"
    assert claims["role"] == "player"
    assert claims["jti"] == "12345"
    assert claims["type"] == ACCESS_TYPE
    assert claims["exp"] > claims["iat"]


def test_refresh_token_roundtrip() -> None:
    settings = get_settings()
    token = create_refresh_token(sub=7, jti=999)
    claims = decode_token(token, REFRESH_TYPE, settings.jwt_refresh_secret)
    assert claims["sub"] == "7"
    assert claims["jti"] == "999"
    assert claims["type"] == REFRESH_TYPE


def test_participant_token_roundtrip() -> None:
    settings = get_settings()
    token = create_participant_token("ABC123", participant_id=1234, nickname="Avenger")
    claims = decode_token(token, PARTICIPANT_TYPE, settings.jwt_secret)
    assert claims["room_code"] == "ABC123"
    assert claims["participant_id"] == "1234"
    assert claims["nickname"] == "Avenger"
    assert claims["type"] == PARTICIPANT_TYPE
    # 4h TTL
    assert (claims["exp"] - claims["iat"]) == 4 * 60 * 60


def test_refresh_secret_does_not_validate_with_access_secret() -> None:
    settings = get_settings()
    refresh = create_refresh_token(sub=1, jti=2)
    with pytest.raises(AuthError) as exc_info:
        decode_token(refresh, REFRESH_TYPE, settings.jwt_secret)
    # Wrong secret → InvalidTokenError → AUTH_REQUIRED
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_wrong_token_type_returns_forbidden() -> None:
    settings = get_settings()
    access = create_access_token(sub=1, role="player", jti=2)
    with pytest.raises(AuthError) as exc_info:
        decode_token(access, REFRESH_TYPE, settings.jwt_secret)
    # Token verifies but ``type`` mismatch → FORBIDDEN
    assert exc_info.value.code == "FORBIDDEN"
    assert exc_info.value.http_status == 403


def test_expired_token_returns_auth_required() -> None:
    settings = get_settings()
    # Hand-craft an expired token rather than time-travelling Python time.
    expired_claims = {
        "sub": "1",
        "role": "player",
        "jti": "2",
        "type": ACCESS_TYPE,
        "iat": int(time.time()) - 3600,
        "exp": int(time.time()) - 60,
    }
    expired = jwt.encode(expired_claims, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(AuthError) as exc_info:
        decode_token(expired, ACCESS_TYPE, settings.jwt_secret)
    assert exc_info.value.code == "AUTH_REQUIRED"
    assert "expired" in (exc_info.value.message or "").lower()


def test_garbled_token_returns_auth_required() -> None:
    settings = get_settings()
    with pytest.raises(AuthError) as exc_info:
        decode_token("not.a.jwt", ACCESS_TYPE, settings.jwt_secret)
    assert exc_info.value.code == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Revocation list
# ---------------------------------------------------------------------------


async def test_revoke_then_check_returns_true() -> None:
    fake = _FakeRedis()
    assert await is_jti_revoked(fake, "abc") is False
    await revoke_jti(fake, "abc", ttl_seconds=120)
    assert await is_jti_revoked(fake, "abc") is True
    # The TTL we passed must have been forwarded to the underlying SET.
    assert fake.store["auth:revoked:abc"][1] == 120


async def test_revoke_clamps_ttl_floor_to_one_second() -> None:
    fake = _FakeRedis()
    await revoke_jti(fake, "x", ttl_seconds=-50)
    assert fake.store["auth:revoked:x"][1] == 1
