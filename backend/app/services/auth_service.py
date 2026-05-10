"""Auth orchestration: register, login, refresh-rotation, logout.

Each method owns its DB transaction (``session.commit()`` at the end).
Snowflake ids — for users, audit rows, and JWT ``jti`` claims — are minted
via ``app.core.ids.get_id_generator``; jtis must be globally unique so
revocation by jti is unambiguous across replicas.

Login is **rate-limited** at the (ip, sha1(email)) tuple per docs/09 — we
hash the email so a single Redis key never reveals the address.

Failed logins do NOT leak whether the email exists: the missing-user branch
runs a dummy verify before raising, giving the same compute profile as a
valid email + wrong password.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.rate_limit import acquire as rate_acquire
from app.core.config import get_settings
from app.core.ids import get_id_generator
from app.core.security import (
    REFRESH_TYPE,
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify,
    hash_password,
    is_jti_revoked,
    revoke_jti,
    verify_password,
)
from app.db.models.audit_log import AuditLog
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.repositories.audit_repo import AuditRepo
from app.repositories.user_repo import UserRepo

# ``capacity = 10`` tokens, refilled at ``10 / 60s`` per docs/09. The 11th
# attempt within a minute lands the requester on RATE_LIMITED.
_LOGIN_CAPACITY = 10
_LOGIN_REFILL_PER_SEC = 10.0 / 60.0


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # access TTL in seconds


def _email_hash(email: str) -> str:
    return hashlib.sha1(email.lower().encode("utf-8")).hexdigest()


def _login_key(ip: str, email: str) -> str:
    return f"rate:login:{ip}:{_email_hash(email)}"


def _build_pair(user: User) -> TokenPair:
    settings = get_settings()
    gen = get_id_generator()
    access_jti = gen.next_id()
    refresh_jti = gen.next_id()
    access = create_access_token(sub=user.id, role=user.role.value, jti=access_jti)
    refresh = create_refresh_token(sub=user.id, jti=refresh_jti)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_ttl_min * 60,
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
) -> User:
    repo = UserRepo(session)
    if await repo.get_by_email(email) is not None:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="email already registered",
            details={"field": "email"},
        )

    gen = get_id_generator()
    user = User(
        id=gen.next_id(),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=UserRole.player,
        is_active=True,
    )
    await repo.add(user)

    await AuditRepo(session).add(
        AuditLog(
            id=gen.next_id(),
            actor_user_id=user.id,
            action="user.registered",
            entity_type="user",
            entity_id=user.id,
            audit_metadata={"email": email},
        )
    )

    await session.commit()
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def login(
    session: AsyncSession,
    redis: Redis,
    *,
    email: str,
    password: str,
    ip: str,
    rate_limit_sha: str,
) -> tuple[User, TokenPair]:
    allowed, _remaining, retry_ms = await rate_acquire(
        redis,
        rate_limit_sha,
        _login_key(ip, email),
        capacity=_LOGIN_CAPACITY,
        refill_per_sec=_LOGIN_REFILL_PER_SEC,
        cost=1,
    )
    if not allowed:
        raise AuthError(
            "RATE_LIMITED",
            429,
            message="too many login attempts",
            details={"retry_after_ms": retry_ms},
        )

    user = await UserRepo(session).get_by_email(email)
    if user is None:
        # Burn the same compute as a real verify so an attacker can't
        # distinguish "no such user" from "wrong password".
        dummy_verify(password)
        raise AuthError("AUTH_REQUIRED", 401, message="invalid credentials")

    if not user.is_active:
        raise AuthError("AUTH_REQUIRED", 401, message="account disabled")

    if not verify_password(password, user.password_hash):
        raise AuthError("AUTH_REQUIRED", 401, message="invalid credentials")

    return user, _build_pair(user)


# ---------------------------------------------------------------------------
# Refresh (rotation)
# ---------------------------------------------------------------------------


async def refresh(
    session: AsyncSession,
    redis: Redis,
    *,
    refresh_token: str,
) -> tuple[User, TokenPair]:
    settings = get_settings()
    claims = decode_token(refresh_token, REFRESH_TYPE, settings.jwt_refresh_secret)

    if await is_jti_revoked(redis, claims["jti"]):
        raise AuthError("AUTH_REQUIRED", 401, message="token revoked")

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("AUTH_REQUIRED", 401, message="malformed token sub") from exc

    user = await UserRepo(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthError("AUTH_REQUIRED", 401, message="user not found or inactive")

    # Rotate: revoke the just-used refresh jti for its remaining lifetime.
    ttl_remaining = max(1, int(claims["exp"]) - int(time.time()))
    await revoke_jti(redis, claims["jti"], ttl_remaining)

    return user, _build_pair(user)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def logout(redis: Redis, *, refresh_token: str) -> None:
    """Revoke the refresh jti carried by ``refresh_token``.

    A malformed/expired token is a silent no-op — there's nothing to revoke
    that wouldn't already be invalid. Access tokens are not blacklisted;
    they expire within 15 minutes.
    """
    settings = get_settings()
    try:
        claims = decode_token(refresh_token, REFRESH_TYPE, settings.jwt_refresh_secret)
    except AuthError:
        return
    ttl_remaining = max(1, int(claims["exp"]) - int(time.time()))
    await revoke_jti(redis, claims["jti"], ttl_remaining)
