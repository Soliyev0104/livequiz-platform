"""Integration tests for the P09 moderation surface.

Six canonical scenarios, all exercising the real Postgres + Redis
testcontainers and the ASGI transport (no mocks):

1. ``test_player_reports_nickname_creates_pending_row`` — guest hits
   ``POST /reports`` and the row turns up in the pending queue.
2. ``test_player_cannot_access_queue`` — non-moderator gets 403 on
   ``GET /moderation/reports``.
3. ``test_dismiss_decision_writes_audit_and_sets_status`` — moderator
   dismisses a report; ``audit_logs`` carries a
   ``moderation.decide.dismiss`` row.
4. ``test_hide_decision_flips_quiz_visibility`` — hide drops the target
   quiz to ``private`` + ``is_published=false``.
5. ``test_mute_closes_target_ws`` — mute triggers a Redis publish on
   ``ws:room:{code}`` and the target participant's WebSocket closes
   with 4002.
6. ``test_publish_with_banned_word_auto_flags`` — quiz with a banned
   word in the title creates a pending report on publish.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.ids import get_id_generator
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.audit_log import AuditLog
from app.db.models.enums import ModerationStatus, UserRole
from app.db.models.moderation_report import ModerationReport
from app.db.models.user import User
from app.main import create_app
from app.ws.connection_manager import ConnectionManager
from app.ws.redis_pubsub import start_pubsub_task, stop_pubsub_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def mod_app(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[tuple[AsyncClient, ConnectionPool]]:
    """Returns an HTTP-only ASGI client + the shared Redis pool."""
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
            yield client, pool
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


@pytest_asyncio.fixture(loop_scope="session")
async def ws_mod_app(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[tuple[AsyncClient, ConnectionPool, ConnectionManager]]:
    """Variant fixture for the mute-close test — wires the WS plumbing.

    The pub/sub listener is the actual bridge that delivers the synthetic
    ``participant.kicked`` envelope produced by ``moderation_service.decide``
    back into the in-process ``ConnectionManager``, which then closes the
    matching socket.
    """
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

    replica_id = uuid.uuid4().hex
    manager = ConnectionManager(replica_id=replica_id)
    pubsub_redis = Redis(connection_pool=pool)
    pubsub_task, _ready = await start_pubsub_task(pubsub_redis, manager)
    app.state.replica_id = replica_id
    app.state.connection_manager = manager
    app.state.pubsub_redis = pubsub_redis
    app.state.pubsub_task = pubsub_task

    transport = ASGIWebSocketTransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client, pool, manager
    finally:
        try:
            await client.aclose()
        except (RuntimeError, Exception):
            pass
        await stop_pubsub_task(pubsub_task)
        try:
            await pubsub_redis.aclose()
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_user(
    migrated_engine, *, email: str, role: UserRole, password: str = "ModPass123!"
) -> int:
    gen = get_id_generator()
    user_id = gen.next_id()
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                display_name=email.split("@")[0],
                role=role,
                is_active=True,
            )
        )
        await s.commit()
    return user_id


async def _login(
    client: AsyncClient, email: str, password: str = "ModPass123!"
) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _single_choice_q(body: str = "Q?") -> dict:
    return {
        "position": 1,
        "body": body,
        "type": "single_choice",
        "time_limit_seconds": 20,
        "points": 1000,
        "options": [
            {"position": 1, "body": "A", "is_correct": False},
            {"position": 2, "body": "B", "is_correct": True},
        ],
    }


async def _publish_quiz(
    client: AsyncClient, token: str, *, title: str = "Mod Quiz"
) -> str:
    create = await client.post(
        "/api/v1/quiz-sets",
        headers=_auth(token),
        json={"title": title, "visibility": "public"},
    )
    assert create.status_code == 201, create.text
    qid = create.json()["id"]
    add_q = await client.post(
        f"/api/v1/quiz-sets/{qid}/questions",
        headers=_auth(token),
        json=_single_choice_q(),
    )
    assert add_q.status_code == 201, add_q.text
    publish = await client.post(
        f"/api/v1/quiz-sets/{qid}/publish", headers=_auth(token)
    )
    assert publish.status_code == 200, publish.text
    return qid


async def _create_room_and_join(
    client: AsyncClient, token: str, quiz_id: str, *, nickname: str
) -> tuple[str, str, str]:
    """Returns ``(room_code, participant_id, participant_token)``."""
    create = await client.post(
        "/api/v1/rooms",
        headers=_auth(token),
        json={"quiz_set_id": quiz_id, "max_players": 50, "settings": {}},
    )
    assert create.status_code == 201, create.text
    code = create.json()["code"]
    join = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": nickname}
    )
    assert join.status_code == 200, join.text
    body = join.json()
    return code, body["participant_id"], body["participant_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_player_reports_nickname_creates_pending_row(
    mod_app, migrated_engine
) -> None:
    client, _ = mod_app
    # Seed: one moderator (for queue read) + one target user.
    await _seed_user(migrated_engine, email="mod1@moderation.example.com", role=UserRole.moderator)
    target_id = await _seed_user(
        migrated_engine, email="target1@moderation.example.com", role=UserRole.player
    )

    # Guest report (no auth header).
    resp = await client.post(
        "/api/v1/reports",
        json={"target_user_id": str(target_id), "reason": "abusive nickname"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["target_user_id"] == str(target_id)
    assert body["reporter_user_id"] is None

    # Moderator can see it in the queue.
    mod_token = await _login(client, "mod1@moderation.example.com")
    queue = await client.get(
        "/api/v1/moderation/reports?status=pending", headers=_auth(mod_token)
    )
    assert queue.status_code == 200, queue.text
    items = queue.json()["items"]
    assert len(items) == 1
    assert items[0]["report"]["id"] == body["id"]
    assert items[0]["target"]["kind"] == "user"
    assert items[0]["target"]["id"] == str(target_id)


async def test_player_cannot_access_queue(mod_app, migrated_engine) -> None:
    client, _ = mod_app
    await _seed_user(migrated_engine, email="p1@moderation.example.com", role=UserRole.player)
    player_token = await _login(client, "p1@moderation.example.com")

    resp = await client.get(
        "/api/v1/moderation/reports?status=pending", headers=_auth(player_token)
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_dismiss_decision_writes_audit_and_sets_status(
    mod_app, migrated_engine
) -> None:
    client, _ = mod_app
    mod_id = await _seed_user(
        migrated_engine, email="mod2@moderation.example.com", role=UserRole.moderator
    )
    target_id = await _seed_user(
        migrated_engine, email="target2@moderation.example.com", role=UserRole.player
    )

    # Player files a report.
    rep = await client.post(
        "/api/v1/reports",
        json={"target_user_id": str(target_id), "reason": "noise"},
    )
    assert rep.status_code == 201
    report_id = rep.json()["id"]

    # Moderator dismisses it.
    mod_token = await _login(client, "mod2@moderation.example.com")
    decide = await client.post(
        f"/api/v1/moderation/reports/{report_id}/decision",
        headers=_auth(mod_token),
        json={"decision": "dismiss", "reason": "spurious"},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["status"] == "dismissed"

    # Status persisted + audit row written.
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        row = await s.get(ModerationReport, int(report_id))
        assert row is not None
        assert row.status == ModerationStatus.dismissed
        assert row.reviewed_by == mod_id

        audit_rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.entity_id == int(report_id))
            )
        ).scalars().all()
        actions = [a.action for a in audit_rows]
        assert "moderation.decide.dismiss" in actions


async def test_hide_decision_flips_quiz_visibility(
    mod_app, migrated_engine
) -> None:
    client, _ = mod_app
    await _seed_user(migrated_engine, email="host3@moderation.example.com", role=UserRole.host)
    await _seed_user(migrated_engine, email="mod3@moderation.example.com", role=UserRole.moderator)

    host_token = await _login(client, "host3@moderation.example.com")
    quiz_id = await _publish_quiz(client, host_token, title="Hide Me")

    # File a report against the quiz.
    rep = await client.post(
        "/api/v1/reports",
        json={"target_quiz_set_id": quiz_id, "reason": "offensive content"},
    )
    assert rep.status_code == 201
    report_id = rep.json()["id"]

    mod_token = await _login(client, "mod3@moderation.example.com")
    decide = await client.post(
        f"/api/v1/moderation/reports/{report_id}/decision",
        headers=_auth(mod_token),
        json={"decision": "hide"},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["status"] == "action_taken"

    # Quiz row should be private + unpublished.
    detail = await client.get(
        f"/api/v1/quiz-sets/{quiz_id}", headers=_auth(host_token)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["visibility"] == "private"
    assert body["is_published"] is False


async def test_publish_with_banned_word_auto_flags(
    mod_app, migrated_engine
) -> None:
    client, _ = mod_app
    await _seed_user(migrated_engine, email="host4@moderation.example.com", role=UserRole.host)
    await _seed_user(migrated_engine, email="mod4@moderation.example.com", role=UserRole.moderator)

    host_token = await _login(client, "host4@moderation.example.com")
    # "fuck" is in ops/moderation/banned_words.json.
    quiz_id = await _publish_quiz(
        client, host_token, title="The fuck quiz of doom"
    )

    mod_token = await _login(client, "mod4@moderation.example.com")
    queue = await client.get(
        "/api/v1/moderation/reports?status=pending", headers=_auth(mod_token)
    )
    assert queue.status_code == 200, queue.text
    items = queue.json()["items"]
    # At least one auto-flagged report against this quiz.
    assert any(
        it["report"]["target_quiz_set_id"] == quiz_id for it in items
    ), f"expected auto-flag on quiz {quiz_id}: items={items}"
    auto_flagged = [
        it for it in items if it["report"]["target_quiz_set_id"] == quiz_id
    ]
    assert any(
        it["report"]["reason"] in {"banned_word", "banned_pattern"}
        for it in auto_flagged
    )


async def test_mute_closes_target_ws(ws_mod_app, migrated_engine) -> None:
    """Mute decision closes the target participant's WS with code 4002.

    Bypasses the httpx-ws ASGI transport (which has an event-loop
    interaction issue when sharing a loop with testcontainers — see the
    pre-existing P06 ``test_websocket.py`` tests) by registering a fake
    :class:`WebSocketConnection` directly with the shared
    :class:`ConnectionManager`. The Redis pub/sub bridge still does the
    real work: ``moderation_service.decide(..., decision="mute")``
    publishes ``participant.kicked`` on ``ws:room:{code}``, the listener
    delivers it to the manager, and the manager translates it into a
    ``ws.close(KICKED_CLOSE_CODE)`` on the matching connection. We
    intercept the close call on our fake socket.
    """
    from app.ws.connection_manager import (
        KICKED_CLOSE_CODE,
        WebSocketConnection,
    )

    client, _pool, manager = ws_mod_app

    await _seed_user(
        migrated_engine, email="host5@moderation.example.com", role=UserRole.host
    )
    await _seed_user(
        migrated_engine, email="mod5@moderation.example.com", role=UserRole.moderator
    )

    host_token = await _login(client, "host5@moderation.example.com")
    quiz_id = await _publish_quiz(client, host_token, title="WS Mute")
    code, participant_id, _ptoken = await _create_room_and_join(
        client, host_token, quiz_id, nickname="MuteVictim"
    )

    # Stand-in WebSocket that records close calls and accepts the
    # informational ``participant.kicked`` frame from broadcast_local.
    class _FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed: list[tuple[int, str | None]] = []

        async def send_text(self, data: str) -> None:
            self.sent.append(data)

        async def close(self, code: int = 1000, reason: str | None = None) -> None:
            self.closed.append((code, reason))

    fake_ws = _FakeWS()
    conn = WebSocketConnection(
        ws=fake_ws,  # type: ignore[arg-type]
        conn_id="fake-conn-1",
        participant_id=int(participant_id),
        nickname="MuteVictim",
        is_host=False,
    )
    await manager.connect(code, conn)
    try:
        room_id = await _room_id_for_code(migrated_engine, code)

        # File a report scoped to the room; the mute branch matches by
        # room_id and kicks every active participant in the room.
        rep = await client.post(
            "/api/v1/reports",
            json={"room_id": room_id, "reason": "noise"},
        )
        assert rep.status_code == 201, rep.text
        report_id = rep.json()["id"]

        mod_token = await _login(client, "mod5@moderation.example.com")
        decide = await client.post(
            f"/api/v1/moderation/reports/{report_id}/decision",
            headers=_auth(mod_token),
            json={"decision": "mute"},
        )
        assert decide.status_code == 200, decide.text

        # Redis publish → pub/sub listener → ConnectionManager.broadcast_local
        # → fake_ws.send_text(...) + fake_ws.close(KICKED_CLOSE_CODE).
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            if fake_ws.closed:
                break
            await asyncio.sleep(0.05)

        assert fake_ws.closed, "ws.close was never called for the muted participant"
        close_code, _reason = fake_ws.closed[0]
        assert close_code == KICKED_CLOSE_CODE, (
            f"expected close code {KICKED_CLOSE_CODE}, got {close_code}"
        )

        # The informational envelope must have reached every member.
        kicked_frames = [
            json.loads(s) for s in fake_ws.sent if '"participant.kicked"' in s
        ]
        assert kicked_frames, f"no participant.kicked frame in {fake_ws.sent!r}"
        assert kicked_frames[0]["payload"]["participant_id"] == participant_id

        # Authoritative: participant.is_kicked flipped in Postgres.
        sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
        async with sm() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT is_kicked FROM room_participants WHERE id = :pid"
                    ),
                    {"pid": int(participant_id)},
                )
            ).scalar_one()
            assert row is True
    finally:
        await manager.disconnect(code, conn)


# ---------------------------------------------------------------------------
# WS helpers
# ---------------------------------------------------------------------------


async def _drain_until_quiet(ws, *, settle_ms: int = 200) -> list[dict]:
    out: list[dict] = []
    while True:
        try:
            raw = await asyncio.wait_for(
                ws.receive_text(), timeout=settle_ms / 1000.0
            )
        except asyncio.TimeoutError:
            return out
        except Exception:
            return out
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue


async def _room_id_for_code(migrated_engine, code: str) -> str:
    """Look up the snowflake ``rooms.id`` for a given Crockford code.

    Returned as a string so the JSON-wire ``ReportCreate`` shape never
    loses snowflake precision when re-serialised by the client.
    """
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        row = (
            await s.execute(
                text("SELECT id FROM rooms WHERE code = :c"), {"c": code}
            )
        ).scalar_one()
    return str(row)
