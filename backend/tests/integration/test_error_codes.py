"""Focused Phase 12 error-code coverage."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache import leaderboard as lb_cache
from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.db.base import Base
from app.db.models.enums import UserRole
from app.main import create_app
from app.services import match_service
from tests.integration._helpers import (
    auth,
    create_published_quiz,
    create_room,
    join,
    login_token,
    make_user,
    register,
    setup_started_match,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def app_client(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[AsyncClient]:
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    async with Redis(connection_pool=pool) as redis:
        await redis.flushdb()
        rate_sha = await load_rate_limit_script(redis)
        admit_sha, release_sha = await load_capacity_scripts(redis)
        leaderboard_sha = await lb_cache.load_script(redis)

    match_service.reset_scheduler_for_tests()
    app = create_app()
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = rate_sha
    app.state.capacity_admit_sha = admit_sha
    app.state.capacity_release_sha = release_sha
    app.state.leaderboard_sha = leaderboard_sha

    from app.ws.connection_manager import ConnectionManager

    sessionmaker = async_sessionmaker(migrated_engine, expire_on_commit=False)
    manager = ConnectionManager(replica_id=uuid.uuid4().hex)
    app.state.connection_manager = manager
    app.state.replica_id = manager.replica_id
    app.state.match_runtime = match_service.MatchRuntime(
        sessionmaker=sessionmaker,
        redis_pool=pool,
        connection_manager=manager,
        capacity_admit_sha=admit_sha,
        capacity_release_sha=release_sha,
        leaderboard_sha=leaderboard_sha,
    )
    app.state.match_scheduler = match_service._scheduler_singleton()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
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
            async with Redis(connection_pool=pool) as redis:
                await redis.flushdb()
            await pool.disconnect()
            match_service.reset_scheduler_for_tests()


def assert_error(resp, status_code: int, code: str) -> dict:
    assert resp.status_code == status_code, resp.text
    body = resp.json()
    assert body["error"]["code"] == code
    assert body["request_id"] is not None
    return body


async def test_auth_required(app_client: AsyncClient) -> None:
    assert_error(await app_client.get("/api/v1/me"), 401, "AUTH_REQUIRED")


async def test_forbidden(app_client: AsyncClient, migrated_engine) -> None:
    await register(app_client, "player-forbidden@livequiz.local")
    player = await login_token(
        app_client, "player-forbidden@livequiz.local", "Password123!"
    )
    admin_id = await make_user(
        migrated_engine, "admin-target@livequiz.local", UserRole.admin
    )
    resp = await app_client.get(f"/api/v1/users/{admin_id}", headers=auth(player))
    assert_error(resp, 403, "FORBIDDEN")


async def test_quiz_not_published(app_client: AsyncClient, migrated_engine) -> None:
    email = "draft-host@livequiz.local"
    await make_user(migrated_engine, email, UserRole.host)
    host = await login_token(app_client, email, "HostPass123!")
    create = await app_client.post(
        "/api/v1/quiz-sets",
        headers=auth(host),
        json={"title": "Draft", "visibility": "public"},
    )
    resp = await app_client.post(
        "/api/v1/rooms",
        headers=auth(host),
        json={"quiz_set_id": create.json()["id"], "max_players": 50, "settings": {}},
    )
    assert_error(resp, 409, "QUIZ_NOT_PUBLISHED")


async def test_room_not_found(app_client: AsyncClient) -> None:
    assert_error(await app_client.get("/api/v1/rooms/ZZZZZZ"), 404, "ROOM_NOT_FOUND")


async def test_room_full(app_client: AsyncClient, migrated_engine) -> None:
    email = "full-host@livequiz.local"
    await make_user(migrated_engine, email, UserRole.host)
    host = await login_token(app_client, email, "HostPass123!")
    quiz_id, _ = await create_published_quiz(app_client, host)
    room = await create_room(app_client, host, quiz_id, max_players=2)
    await join(app_client, room["code"], "p1")
    await join(app_client, room["code"], "p2")
    resp = await app_client.post(
        f"/api/v1/rooms/{room['code']}/join", json={"nickname": "p3"}
    )
    assert_error(resp, 409, "ROOM_FULL")


async def test_room_not_joinable(app_client: AsyncClient, migrated_engine) -> None:
    started = await setup_started_match(app_client, migrated_engine)
    resp = await app_client.post(
        f"/api/v1/rooms/{started['room']['code']}/start",
        headers=auth(started["host_token"]),
    )
    assert_error(resp, 409, "ROOM_NOT_JOINABLE")


async def test_duplicate_nickname(app_client: AsyncClient, migrated_engine) -> None:
    email = "dupe-host@livequiz.local"
    await make_user(migrated_engine, email, UserRole.host)
    host = await login_token(app_client, email, "HostPass123!")
    quiz_id, _ = await create_published_quiz(app_client, host)
    room = await create_room(app_client, host, quiz_id)
    await join(app_client, room["code"], "Same")
    resp = await app_client.post(
        f"/api/v1/rooms/{room['code']}/join", json={"nickname": "Same"}
    )
    assert_error(resp, 409, "DUPLICATE_NICKNAME")


async def test_question_closed(app_client: AsyncClient, migrated_engine) -> None:
    started = await setup_started_match(
        app_client, migrated_engine, time_limit_seconds=1
    )
    await asyncio.sleep(1.6)
    mq = started["match_question"]
    resp = await app_client.post(
        f"/api/v1/matches/{started['match_id']}/answers",
        headers={**auth(started["player_token"]), "X-Request-ID": uuid.uuid4().hex},
        json={
            "match_question_id": str(mq.id),
            "selected_option_ids": [str(started["correct_option_id"])],
        },
    )
    assert_error(resp, 409, "QUESTION_CLOSED")


@pytest.mark.skip(
    reason=(
        "ANSWER_ALREADY_SUBMITTED is an internal consistency guard; public "
        "retries resolve idempotently with 202."
    )
)
async def test_answer_already_submitted_code_is_internal_only() -> None:
    pass


async def test_duplicate_answer_public_api_resolves_idempotently(
    app_client: AsyncClient, migrated_engine
) -> None:
    started = await setup_started_match(app_client, migrated_engine)
    mq = started["match_question"]
    first = await app_client.post(
        f"/api/v1/matches/{started['match_id']}/answers",
        headers={**auth(started["player_token"]), "X-Request-ID": uuid.uuid4().hex},
        json={
            "match_question_id": str(mq.id),
            "selected_option_ids": [str(started["correct_option_id"])],
        },
    )
    assert first.status_code == 202, first.text
    second = await app_client.post(
        f"/api/v1/matches/{started['match_id']}/answers",
        headers={**auth(started["player_token"]), "X-Request-ID": uuid.uuid4().hex},
        json={"match_question_id": str(mq.id), "selected_option_ids": []},
    )
    assert second.status_code == 202, second.text
    assert second.json()["submission_id"] == first.json()["submission_id"]


async def test_rate_limited_retry_after(app_client: AsyncClient) -> None:
    await register(app_client, "rate-limited@livequiz.local", "Right1234!")
    for _ in range(10):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"email": "rate-limited@livequiz.local", "password": "Wrong1234!"},
        )
        assert resp.status_code == 401
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "rate-limited@livequiz.local", "password": "Wrong1234!"},
    )
    body = assert_error(resp, 429, "RATE_LIMITED")
    assert resp.headers["Retry-After"]
    assert body["error"]["details"]["retry_after_ms"] > 0


async def test_validation_error(app_client: AsyncClient) -> None:
    resp = await app_client.post("/api/v1/auth/register", json={"email": "bad"})
    assert_error(resp, 422, "VALIDATION_ERROR")


async def test_admin_metrics(app_client: AsyncClient, migrated_engine) -> None:
    await register(app_client, "metrics-player@livequiz.local")
    player = await login_token(app_client, "metrics-player@livequiz.local", "Password123!")
    denied = await app_client.get("/api/v1/admin/metrics", headers=auth(player))
    assert_error(denied, 403, "FORBIDDEN")

    await make_user(
        migrated_engine, "metrics-admin@livequiz.local", UserRole.admin, "AdminPass123!"
    )
    admin = await login_token(app_client, "metrics-admin@livequiz.local", "AdminPass123!")
    ok = await app_client.get("/api/v1/admin/metrics", headers=auth(admin))
    assert ok.status_code == 200, ok.text
    assert set(ok.json()) == {
        "total_users",
        "total_quiz_sets",
        "published_quiz_sets",
        "total_rooms",
        "total_matches",
        "completed_matches",
    }
    assert all(isinstance(value, int) for value in ok.json().values())
