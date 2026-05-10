"""Seed the four canonical demo users (admin, host, player1, player2).

Passwords are hashed with Argon2id at reduced cost so dev/test boots fast;
production hashing parameters land in P03's `app.core.security`. Idempotent:
skips users that already exist by email.
"""

from __future__ import annotations

from passlib.hash import argon2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import get_id_generator
from app.db.models.enums import UserRole
from app.db.models.user import User

# Reduced Argon2id cost for dev/test seed. P03's security module will own the
# production parameters; keeping seed under ~100ms total avoids slowing CI.
_argon2 = argon2.using(rounds=2, memory_cost=8, parallelism=1)


SEED_USERS: list[dict[str, object]] = [
    {
        "email": "admin@livequiz.local",
        "password": "admin",
        "display_name": "Admin",
        "role": UserRole.admin,
    },
    {
        "email": "host@livequiz.local",
        "password": "host",
        "display_name": "Host",
        "role": UserRole.host,
    },
    {
        "email": "player1@livequiz.local",
        "password": "player",
        "display_name": "Player One",
        "role": UserRole.player,
    },
    {
        "email": "player2@livequiz.local",
        "password": "player",
        "display_name": "Player Two",
        "role": UserRole.player,
    },
]


async def run(session: AsyncSession) -> dict[str, User]:
    """Insert any missing seed users; return a map of email → User."""
    gen = get_id_generator()
    out: dict[str, User] = {}
    for spec in SEED_USERS:
        email = str(spec["email"])
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            out[email] = existing
            continue
        user = User(
            id=gen.next_id(),
            email=email,
            password_hash=_argon2.hash(str(spec["password"])),
            display_name=str(spec["display_name"]),
            role=spec["role"],  # type: ignore[arg-type]
            is_active=True,
        )
        session.add(user)
        await session.flush()
        out[email] = user
    return out
