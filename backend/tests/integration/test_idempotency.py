"""Integration test: Redis idempotency cache short-circuits the DB tx.

The first ``POST /matches/{id}/answers`` writes both an
``answer_submissions`` row AND ``idem:{request_id}`` in Redis. A retry
with the same ``X-Request-ID`` must return identically without opening
a new transaction — we assert this by:

1. Pre-populating the Redis idempotency key with a *different*
   response payload before any DB writes happen.
2. Submitting under that ``X-Request-ID``.
3. Asserting the response equals the cached payload, NOT what the DB
   transaction would have produced.
4. Asserting no ``answer_submissions`` row exists for that match — the
   cache hit short-circuited before any INSERT.

The companion deadline / unique-constraint races are covered by
``test_answer_submission.py``; this file focuses solely on the cache
path.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache import leaderboard as lb_cache
from app.cache.keys import idempotency_key
from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.answer_submission import AnswerSubmission
from app.db.models.enums import UserRole
from app.db.models.match_question import MatchQuestion
from app.db.models.user import User
from app.main import create_app
from app.services import match_service

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def app_client(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[tuple[AsyncClient, ConnectionPool]]:
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    async with Redis(connection_pool=pool) as r:
        await r.flushdb()
        rate_sha = await load_rate_limit_script(r)
        admit_sha, release_sha = await load_capacity_scripts(r)
        leaderboard_sha = await lb_cache.load_script(r)

    match_service.reset_scheduler_for_tests()
    app = create_app()
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = rate_sha
    app.state.capacity_admit_sha = admit_sha
    app.state.capacity_release_sha = release_sha
    app.state.leaderboard_sha = leaderboard_sha

    sessionmaker = async_sessionmaker(migrated_engine, expire_on_commit=False)
    from app.ws.connection_manager import ConnectionManager

    manager = ConnectionManager(replica_id=uuid.uuid4().hex)
    app.state.connection_manager = manager
    app.state.replica_id = manager.replica_id
    runtime = match_service.MatchRuntime(
        sessionmaker=sessionmaker,
        redis_pool=pool,
        connection_manager=manager,
        capacity_admit_sha=admit_sha,
        capacity_release_sha=release_sha,
        leaderboard_sha=leaderboard_sha,
    )
    app.state.match_runtime = runtime
    app.state.match_scheduler = match_service._scheduler_singleton()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, pool
        finally:
            try:
                await app.state.match_scheduler.cancel_all()
            except Exception:
                pass
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
            match_service.reset_scheduler_for_tests()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_host(migrated_engine, email: str) -> int:
    from app.core.ids import get_id_generator

    user_id = get_id_generator().next_id()
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password("HostPass123!"),
                display_name="Host",
                role=UserRole.host,
                is_active=True,
            )
        )
        await s.commit()
    return user_id


async def _login(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "HostPass123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _setup(client: AsyncClient, migrated_engine) -> tuple[str, int, int]:
    """Return ``(player_token, match_id, match_question_id)``."""
    import asyncio

    email = f"host-{uuid.uuid4().hex[:6]}@a.test"
    await _make_host(migrated_engine, email)
    host_token = await _login(client, email)

    create = await client.post(
        "/api/v1/quiz-sets",
        headers=_auth(host_token),
        json={"title": "Idem Quiz", "visibility": "public"},
    )
    quiz_id = create.json()["id"]
    add_q = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(host_token),
        json={
            "position": 1,
            "body": "Q",
            "type": "single_choice",
            "time_limit_seconds": 30,
            "points": 1000,
            "options": [
                {"position": 1, "body": "A", "is_correct": False},
                {"position": 2, "body": "B", "is_correct": True},
            ],
        },
    )
    assert add_q.status_code == 201, add_q.text
    publish = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(host_token)
    )
    assert publish.status_code == 200

    room = await client.post(
        "/api/v1/rooms",
        headers=_auth(host_token),
        json={"quiz_set_id": quiz_id, "max_players": 10, "settings": {}},
    )
    code = room.json()["code"]

    join = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": "PlayerA"}
    )
    player_token = join.json()["participant_token"]

    start = await client.post(
        f"/api/v1/rooms/{code}/start", headers=_auth(host_token)
    )
    match_id = int(start.json()["match_id"])

    # Wait for arm_question to populate started_at.
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    deadline = asyncio.get_running_loop().time() + 5.0
    mq = None
    while True:
        async with sm() as s:
            stmt = select(MatchQuestion).where(
                MatchQuestion.match_id == match_id,
                MatchQuestion.position == 1,
            )
            mq = (await s.execute(stmt)).scalar_one_or_none()
        if mq is not None and mq.started_at is not None:
            break
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("question never armed")
        await asyncio.sleep(0.05)

    return player_token, match_id, mq.id


async def test_idempotency_cache_short_circuits_db(
    app_client: tuple[AsyncClient, ConnectionPool], migrated_engine
) -> None:
    client, pool = app_client
    player_token, match_id, mq_id = await _setup(client, migrated_engine)

    request_id = uuid.uuid4().hex
    fake_response = {
        "submission_id": "999000111",
        "accepted": True,
        "is_correct": False,  # deliberately not what a real submit would yield
        "score_awarded": 42,
        "response_time_ms": 4242,
        "leaderboard_rank": 7,
    }

    # Pre-populate the cache. The submit handler must read this and
    # short-circuit; a fresh DB tx would compute is_correct=True and a
    # >0 score_awarded, neither of which match this payload.
    async with Redis(connection_pool=pool) as r:
        await r.set(idempotency_key(request_id), json.dumps(fake_response), ex=3600)

    resp = await client.post(
        f"/api/v1/matches/{match_id}/answers",
        headers={**_auth(player_token), "X-Request-ID": request_id},
        json={
            "match_question_id": str(mq_id),
            "selected_option_ids": [],
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["submission_id"] == fake_response["submission_id"]
    assert body["score_awarded"] == fake_response["score_awarded"]
    assert body["response_time_ms"] == fake_response["response_time_ms"]
    assert body["is_correct"] == fake_response["is_correct"]

    # No DB submission row should exist — the cache hit returned before
    # the answer-submission transaction ever started.
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        rows = list(
            (
                await s.execute(
                    select(AnswerSubmission).where(
                        AnswerSubmission.match_id == match_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert rows == [], "cache hit must not write to Postgres"
