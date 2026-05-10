"""End-to-end auth-flow integration test.

Spins up a real Postgres + Redis via testcontainers (provided by
``conftest.py``), boots the FastAPI app via ``create_app()``, wires the
testcontainer engine + redis pool onto ``app.state``, and drives the
public HTTP surface through ``httpx.AsyncClient + ASGITransport``.

Lifespan is deliberately *not* run (httpx's ASGITransport does not
deliver lifespan events) so the app does not try to reach docker-compose
hostnames during tests.

Each test gets a fresh state: TRUNCATE on every Postgres table and
FLUSHDB on Redis, both done in the ``app_client`` fixture's teardown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache.rate_limit import load_script as load_rate_limit_script
from app.core.security import hash_password
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
) -> AsyncIterator[AsyncClient]:
    """Function-scoped FastAPI client backed by testcontainer Postgres + Redis.

    Cleans Postgres (TRUNCATE) and Redis (FLUSHDB) on teardown so each test
    sees a deterministic blank slate, including a freshly empty rate-limit
    bucket.
    """
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)

    # Pre-load the Lua script so EVALSHA inside the login endpoint succeeds.
    async with Redis(connection_pool=pool) as r:
        await r.flushdb()
        sha = await load_rate_limit_script(r)

    app = create_app()
    # httpx's ASGITransport does not deliver lifespan events, so we
    # populate app.state ourselves.
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = sha

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            # Reset Postgres + Redis for the next test.
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


async def _register(client: AsyncClient, email: str, password: str = "Password123!", display_name: str = "U") -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    return (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
    ).json()


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


async def test_register_returns_user_public(app_client: AsyncClient) -> None:
    body = await _register(app_client, "alice@livequiz.local")
    assert body["email"] == "alice@livequiz.local"
    assert body["display_name"] == "U"
    assert body["role"] == UserRole.player.value
    # Snowflake id is stringified for JSON safety.
    assert isinstance(body["id"], str)
    assert body["id"].isdigit()


async def test_register_duplicate_returns_validation_error(app_client: AsyncClient) -> None:
    await _register(app_client, "dup@livequiz.local")
    resp = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "dup@livequiz.local",
            "password": "Password123!",
            "display_name": "U",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["request_id"] is not None


async def test_login_then_me_returns_user(app_client: AsyncClient) -> None:
    user = await _register(app_client, "bob@livequiz.local", "BobPass123!")
    tokens = await _login(app_client, "bob@livequiz.local", "BobPass123!")
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60

    me = await app_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == user["id"]
    assert body["email"] == "bob@livequiz.local"


async def test_me_without_token_returns_401(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_login_wrong_password_returns_auth_required(app_client: AsyncClient) -> None:
    await _register(app_client, "pw@livequiz.local", "Right1234!")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "pw@livequiz.local", "password": "Wrong1234!"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_login_unknown_email_returns_same_envelope(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@livequiz.local", "password": "anything-1234"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Refresh rotation + logout revocation
# ---------------------------------------------------------------------------


async def test_refresh_rotates_and_old_token_is_rejected(app_client: AsyncClient) -> None:
    await _register(app_client, "rot@livequiz.local", "Pass12345!")
    tokens = await _login(app_client, "rot@livequiz.local", "Pass12345!")

    new = await app_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert new.status_code == 200, new.text
    new_tokens = new.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # New access works.
    me = await app_client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert me.status_code == 200

    # Old refresh is rejected.
    replay = await app_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_logout_revokes_refresh(app_client: AsyncClient) -> None:
    await _register(app_client, "out@livequiz.local", "Pass12345!")
    tokens = await _login(app_client, "out@livequiz.local", "Pass12345!")

    resp = await app_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 204

    replay = await app_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401


async def test_logout_without_access_returns_401(app_client: AsyncClient) -> None:
    await _register(app_client, "nax@livequiz.local", "Pass12345!")
    tokens = await _login(app_client, "nax@livequiz.local", "Pass12345!")

    resp = await app_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


async def test_login_rate_limit_triggers_after_eleventh_attempt(app_client: AsyncClient) -> None:
    await _register(app_client, "rl@livequiz.local", "Pass12345!")

    # 10 wrong-password attempts each consume one token.
    for _ in range(10):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"email": "rl@livequiz.local", "password": "Wrong1234!"},
        )
        assert resp.status_code == 401, resp.text

    # 11th attempt — bucket empty → RATE_LIMITED.
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "rl@livequiz.local", "password": "Wrong1234!"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["details"]["retry_after_ms"] > 0


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------


async def test_users_endpoint_requires_admin(app_client: AsyncClient, migrated_engine) -> None:
    """Player → 403, admin → 200 for GET /users/{id}."""
    # A player registers via the public endpoint.
    await _register(app_client, "p@livequiz.local", "Pass12345!")
    player_tokens = await _login(app_client, "p@livequiz.local", "Pass12345!")

    # Insert an admin directly via the engine (registration only mints
    # players).
    from app.core.ids import get_id_generator

    gen = get_id_generator()
    admin_id = gen.next_id()
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            User(
                id=admin_id,
                email="admin-role@livequiz.local",
                password_hash=hash_password("AdminPass123!"),
                display_name="Admin",
                role=UserRole.admin,
                is_active=True,
            )
        )
        await s.commit()
    admin_tokens = await _login(app_client, "admin-role@livequiz.local", "AdminPass123!")

    # Player cannot read.
    resp = await app_client.get(
        f"/api/v1/users/{admin_id}",
        headers={"Authorization": f"Bearer {player_tokens['access_token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # Admin can.
    resp = await app_client.get(
        f"/api/v1/users/{admin_id}",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(admin_id)
    assert body["role"] == UserRole.admin.value


async def test_audit_log_row_inserted_on_register(
    app_client: AsyncClient, migrated_engine
) -> None:
    body = await _register(app_client, "audit@livequiz.local")
    user_id = int(body["id"])
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT action, entity_type, entity_id "
                    "FROM audit_logs WHERE actor_user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).fetchall()
    assert any(r[0] == "user.registered" for r in rows)
