"""Integration tests for the P05 rooms surface.

Five canonical scenarios:

1. ``test_create_room_rejects_draft_quiz`` — host who hasn't published
   the quiz gets ``QUIZ_NOT_PUBLISHED`` (409).
2. ``test_create_then_join_writes_redis_snapshot`` — Redis
   ``room:{code}:state`` reflects the join, with ``player_count == 1``
   and the nickname in the ``participants`` list.
3. ``test_concurrent_same_nickname_one_wins`` — two simultaneous joins
   with the same nickname; exactly one wins, the other gets
   ``DUPLICATE_NICKNAME``, and the Redis capacity counter ends at 1
   (compensating decrement on the loser).
4. ``test_capacity_overflow_rejected_by_lua`` — ``max_players=2`` accepts
   two joins and rejects the third with ``ROOM_FULL`` (the Postgres
   table never sees a third row, because Lua admission gates first).
5. ``test_join_returns_decodable_participant_token`` — the issued token
   round-trips through ``decode_token`` with the right ``room_code``,
   ``participant_id``, ``nickname`` and ``type=participant``.

Reuses the testcontainer harness from ``test_quiz_crud.py``: a real
Postgres + Redis under FastAPI's ASGI transport, TRUNCATE+FLUSHDB
teardown. The fixture also pre-loads the P05 capacity Lua and stashes
the SHAs on ``app.state``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.config import get_settings
from app.core.security import PARTICIPANT_TYPE, decode_token, hash_password
from app.db.base import Base
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.main import create_app

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def app_client(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[tuple[AsyncClient, str]]:
    """Yields ``(client, redis_url)`` so tests can poke Redis directly."""
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)

    async with Redis(connection_pool=pool) as r:
        await r.flushdb()
        rate_sha = await load_rate_limit_script(r)
        admit_sha, release_sha = await load_capacity_scripts(r)

    app = create_app()
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = rate_sha
    app.state.capacity_admit_sha = admit_sha
    app.state.capacity_release_sha = release_sha

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, redis_url
        finally:
            table_names = ", ".join(
                f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables)
            )
            async with migrated_engine.begin() as conn:
                await conn.execute(
                    text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
                )
            async with Redis(connection_pool=pool) as r:
                await r.flushdb()
            await pool.disconnect()


# ---------------------------------------------------------------------------
# Helpers (mirrors test_quiz_crud.py)
# ---------------------------------------------------------------------------


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _make_host(
    migrated_engine, email: str, password: str = "HostPass123!"
) -> int:
    from app.core.ids import get_id_generator

    gen = get_id_generator()
    user_id = gen.next_id()
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                display_name="Host",
                role=UserRole.host,
                is_active=True,
            )
        )
        await s.commit()
    return user_id


async def _host_token(
    client: AsyncClient, migrated_engine, email: str = "host@rooms.example.com"
) -> tuple[int, str]:
    user_id = await _make_host(migrated_engine, email)
    tokens = await _login(client, email, "HostPass123!")
    return user_id, tokens["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _single_choice_q() -> dict:
    return {
        "position": 1,
        "body": "Q?",
        "type": "single_choice",
        "time_limit_seconds": 20,
        "points": 1000,
        "options": [
            {"position": 1, "body": "A", "is_correct": False},
            {"position": 2, "body": "B", "is_correct": True},
        ],
    }


async def _create_published_quiz(client: AsyncClient, token: str) -> str:
    """Create a quiz, attach one valid question, publish; return quiz_id."""
    create = await client.post(
        "/api/v1/quiz-sets",
        headers=_auth(token),
        json={"title": "Live Quiz", "visibility": "public"},
    )
    assert create.status_code == 201, create.text
    quiz_id = create.json()["id"]

    add_q = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=_single_choice_q(),
    )
    assert add_q.status_code == 201, add_q.text

    publish = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert publish.status_code == 200, publish.text
    return quiz_id


async def _create_room(
    client: AsyncClient, token: str, quiz_id: str, *, max_players: int = 50
) -> dict:
    resp = await client.post(
        "/api/v1/rooms",
        headers=_auth(token),
        json={
            "quiz_set_id": quiz_id,
            "max_players": max_players,
            "settings": {},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_room_rejects_draft_quiz(
    app_client: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = app_client
    _, token = await _host_token(client, migrated_engine)

    # Create a quiz but never publish it.
    create = await client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "Draft"}
    )
    quiz_id = create.json()["id"]

    resp = await client.post(
        "/api/v1/rooms",
        headers=_auth(token),
        json={"quiz_set_id": quiz_id, "max_players": 50, "settings": {}},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error"]["code"] == "QUIZ_NOT_PUBLISHED"


async def test_create_then_join_writes_redis_snapshot(
    app_client: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, redis_url = app_client
    _, token = await _host_token(
        client, migrated_engine, email="snap@rooms.example.com"
    )
    quiz_id = await _create_published_quiz(client, token)
    room = await _create_room(client, token, quiz_id)
    code = room["code"]
    assert len(code) == 6
    # Crockford excludes I, L, O, U
    forbidden = set("ILOU")
    assert not (set(code) & forbidden), f"code {code!r} contains forbidden char"

    join = await client.post(
        f"/api/v1/rooms/{code}/join",
        json={"nickname": "Avenger"},
    )
    assert join.status_code == 200, join.text
    body = join.json()
    assert body["nickname"] == "Avenger"
    assert body["code"] == code
    assert body["ws_url"].startswith(f"/ws/rooms/{code}?token=")

    # Snapshot in Redis must reflect the join.
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    async with Redis(connection_pool=pool) as r:
        raw = await r.get(f"room:{code}:state")
        counter = await r.get(f"room:{code}:participants_count")
    await pool.disconnect()

    assert raw is not None, "snapshot key missing from Redis"
    snap = json.loads(raw)
    assert snap["room"]["code"] == code
    assert snap["room"]["status"] == "lobby"
    assert snap["room"]["player_count"] == 1
    assert len(snap["participants"]) == 1
    assert snap["participants"][0]["nickname"] == "Avenger"
    assert counter == "1"


async def test_concurrent_same_nickname_one_wins(
    app_client: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, redis_url = app_client
    _, token = await _host_token(
        client, migrated_engine, email="dupe@rooms.example.com"
    )
    quiz_id = await _create_published_quiz(client, token)
    room = await _create_room(client, token, quiz_id)
    code = room["code"]

    # Fire two joins with the same nickname concurrently.
    nick = "Marvel"
    a, b = await asyncio.gather(
        client.post(f"/api/v1/rooms/{code}/join", json={"nickname": nick}),
        client.post(f"/api/v1/rooms/{code}/join", json={"nickname": nick}),
    )

    statuses = sorted([a.status_code, b.status_code])
    assert statuses == [200, 409], f"got {statuses}: {a.text=} {b.text=}"

    loser = a if a.status_code == 409 else b
    assert loser.json()["error"]["code"] == "DUPLICATE_NICKNAME"

    # Compensating decrement must have run, so the counter reflects the
    # one successful seat — not two phantom seats.
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    async with Redis(connection_pool=pool) as r:
        counter = await r.get(f"room:{code}:participants_count")
        snap = json.loads(await r.get(f"room:{code}:state"))
    await pool.disconnect()

    assert counter == "1", f"counter must be 1, got {counter}"
    assert snap["room"]["player_count"] == 1


async def test_capacity_overflow_rejected_by_lua(
    app_client: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = app_client
    _, token = await _host_token(
        client, migrated_engine, email="cap@rooms.example.com"
    )
    quiz_id = await _create_published_quiz(client, token)
    room = await _create_room(client, token, quiz_id, max_players=2)
    code = room["code"]

    r1 = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": "p1"}
    )
    r2 = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": "p2"}
    )
    r3 = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": "p3"}
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 409, r3.text
    assert r3.json()["error"]["code"] == "ROOM_FULL"

    # Postgres should hold exactly 2 participants (Lua kept the third
    # out before any DB write).
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        result = await s.execute(
            text(
                "SELECT count(*) FROM room_participants WHERE room_id = "
                "(SELECT id FROM rooms WHERE code = :c)"
            ),
            {"c": code},
        )
        count = result.scalar_one()
    assert count == 2


async def test_join_returns_decodable_participant_token(
    app_client: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = app_client
    _, token = await _host_token(
        client, migrated_engine, email="tok@rooms.example.com"
    )
    quiz_id = await _create_published_quiz(client, token)
    room = await _create_room(client, token, quiz_id)
    code = room["code"]

    join = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": "DecodeMe"}
    )
    assert join.status_code == 200, join.text
    body = join.json()

    settings = get_settings()
    claims = decode_token(
        body["participant_token"], PARTICIPANT_TYPE, settings.jwt_secret
    )
    assert claims["type"] == "participant"
    assert claims["room_code"] == code
    assert claims["participant_id"] == body["participant_id"]
    assert claims["nickname"] == "DecodeMe"
    assert "exp" in claims and "iat" in claims
