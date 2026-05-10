"""Integration tests for the P06 WebSocket surface.

Connects through ASGITransport so a real Redis testcontainer + the
P05 in-process Postgres back the snapshot path. The lifespan is not
invoked by ASGITransport, so the fixture wires every ``app.state``
attribute the WS endpoint reads — engine, redis_pool, all three Lua
SHAs, the connection manager, and the per-replica pub/sub listener.

Coverage:

- ``test_connect_receive_snapshot_and_heartbeat_ack`` — golden path:
  participant token → ``room.snapshot`` → ``room.heartbeat`` round-trip
  including ``server_now`` for clock-skew estimation.
- ``test_room_code_mismatch_rejected`` — participant token issued for
  one room cannot connect to another; server closes 4401 before
  ``ws.accept`` so the handshake fails.
- ``test_invalid_token_rejected`` — token signed with the wrong
  secret is rejected at handshake.
- ``test_question_started_omits_correct_flags`` — the Pydantic model
  for ``question.started`` options forbids ``is_correct``/``explanation``
  and the JSON schema agrees.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import jwt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from httpx_ws import WebSocketDisconnect, WebSocketUpgradeError, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.config import get_settings
from app.core.security import (
    PARTICIPANT_TYPE,
    create_participant_token,
    hash_password,
)
from app.db.base import Base
from app.db.models.enums import UserRole
from app.db.models.user import User
from app.main import create_app
from app.ws.connection_manager import ConnectionManager
from app.ws.messages import QuestionStartedMessage, QuestionStartedOption
from app.ws.redis_pubsub import start_pubsub_task, stop_pubsub_task

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def ws_app(
    migrated_engine,
    redis_container: RedisContainer,
) -> AsyncIterator[tuple[AsyncClient, str]]:
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
        yield client, redis_url
    finally:
        # httpx-ws's ASGI transport uses an internal anyio TaskGroup;
        # closing it from a different anyio context (pytest-asyncio
        # session loop) raises RuntimeError("Attempted to exit cancel
        # scope in a different task than it was entered in"). The state
        # is already torn down by the time we get here, so suppress.
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


async def _make_host(migrated_engine, email: str, password: str = "WSPass123!") -> int:
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
                display_name="WSHost",
                role=UserRole.host,
                is_active=True,
            )
        )
        await s.commit()
    return user_id


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


async def _login(client: AsyncClient, email: str, password: str = "WSPass123!") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _create_published_quiz(client: AsyncClient, token: str) -> str:
    create = await client.post(
        "/api/v1/quiz-sets",
        headers=_auth(token),
        json={"title": "WS Quiz", "visibility": "public"},
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


async def _create_room_and_join(
    client: AsyncClient, token: str, quiz_id: str, *, nickname: str
) -> tuple[str, str]:
    """Create a room and join one player. Returns ``(room_code, ws_token)``."""
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
    return code, join.json()["participant_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_connect_receive_snapshot_and_heartbeat_ack(
    ws_app: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = ws_app
    await _make_host(migrated_engine, "ws-snap@example.com")
    host_token = await _login(client, "ws-snap@example.com")
    quiz_id = await _create_published_quiz(client, host_token)
    code, ptoken = await _create_room_and_join(
        client, host_token, quiz_id, nickname="Avenger"
    )

    url = f"http://test/ws/rooms/{code}?token={ptoken}"
    async with aconnect_ws(url, client) as ws:
        # NOTE: do not wrap ``ws.receive_text`` in ``asyncio.wait_for`` —
        # httpx-ws's ASGI transport runs the ASGI app inside an anyio
        # TaskGroup, and ``asyncio.wait_for`` cancels across tasks in a
        # way that anyio rejects with "Attempted to exit cancel scope
        # in a different task than it was entered in". httpx-ws gives
        # us a built-in receive timeout via ``keepalive_ping_timeout``
        # / ``max_message_size_bytes``, but for our purposes the test
        # blocks safely on ``receive_text`` because the server's first
        # frame is the snapshot.
        snap = json.loads(await ws.receive_text())
        assert snap["type"] == "room.snapshot"
        assert snap["payload"]["room"]["code"] == code
        assert snap["payload"]["room"]["player_count"] == 1
        assert snap["payload"]["participants"][0]["nickname"] == "Avenger"

        await ws.send_text(json.dumps({"type": "room.heartbeat", "payload": {}}))

        # Pop messages until we find the ack; ``participant.joined``
        # may arrive interleaved depending on event-loop ordering.
        ack = None
        for _ in range(5):
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "room.heartbeat.ack":
                ack = msg
                break
        assert ack is not None, "did not receive room.heartbeat.ack"
        assert "server_now" in ack["payload"]


async def test_room_code_mismatch_rejected(
    ws_app: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = ws_app
    await _make_host(migrated_engine, "ws-mis@example.com")
    host_token = await _login(client, "ws-mis@example.com")
    quiz_id = await _create_published_quiz(client, host_token)
    code, ptoken = await _create_room_and_join(
        client, host_token, quiz_id, nickname="Marvel"
    )

    # Forge a participant token that targets a *different* room code.
    bad_token = create_participant_token(
        room_code="BADBAD",
        participant_id=12345,
        nickname="Imposter",
    )
    url = f"http://test/ws/rooms/{code}?token={bad_token}"
    # Server closes pre-accept with code 4401. With the ASGI transport
    # this surfaces as ``WebSocketDisconnect`` carrying the close code;
    # against a real wsgi-ws server it would raise
    # ``WebSocketUpgradeError`` instead — we accept either.
    with pytest.raises((WebSocketDisconnect, WebSocketUpgradeError)) as excinfo:
        async with aconnect_ws(url, client):
            pass
    if isinstance(excinfo.value, WebSocketDisconnect):
        assert excinfo.value.code == 4401

    # The legit token still works — sanity check the per-test state was
    # not corrupted by the rejection above.
    ok_url = f"http://test/ws/rooms/{code}?token={ptoken}"
    async with aconnect_ws(ok_url, client) as ws:
        first = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
        assert json.loads(first)["type"] == "room.snapshot"


async def test_invalid_token_rejected(
    ws_app: tuple[AsyncClient, str], migrated_engine
) -> None:
    client, _ = ws_app
    await _make_host(migrated_engine, "ws-bad@example.com")
    host_token = await _login(client, "ws-bad@example.com")
    quiz_id = await _create_published_quiz(client, host_token)
    code, _ = await _create_room_and_join(
        client, host_token, quiz_id, nickname="Solo"
    )

    settings = get_settings()
    # Same shape as a participant token, but signed with a wrong key.
    forged = jwt.encode(
        {
            "type": PARTICIPANT_TYPE,
            "room_code": code,
            "participant_id": "999",
            "nickname": "Forged",
            "iat": 0,
            "exp": 99999999999,
        },
        "definitely-not-the-server-secret",
        algorithm="HS256",
    )
    assert forged.split(".")[0]  # syntactically valid token
    assert settings.jwt_secret != "definitely-not-the-server-secret"

    url = f"http://test/ws/rooms/{code}?token={forged}"
    with pytest.raises((WebSocketDisconnect, WebSocketUpgradeError)) as excinfo:
        async with aconnect_ws(url, client):
            pass
    if isinstance(excinfo.value, WebSocketDisconnect):
        assert excinfo.value.code == 4401


def _collect_property_names(schema: dict) -> set[str]:
    """Walk a JSON schema and gather every ``properties`` key it declares."""
    out: set[str] = set()
    if not isinstance(schema, dict):
        return out
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            out.update(value.keys())
        if isinstance(value, dict):
            out |= _collect_property_names(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    out |= _collect_property_names(item)
    return out


async def test_question_started_omits_correct_flags() -> None:
    """``question.started`` schema must not leak the answer key.

    Three checks:

    1. The ``QuestionStartedOption`` JSON schema declares exactly
       ``id`` and ``body``, with ``additionalProperties: False``.
    2. The full ``question.started`` message schema, walked
       recursively for property names, never declares a property
       called ``is_correct`` or ``explanation``. (We can't text-grep
       the rendered schema because Pydantic emits docstrings into
       ``description`` — and this docstring legitimately mentions
       both words.)
    3. Building a ``QuestionStartedMessage`` from a payload that
       sneaks ``is_correct`` in raises a validation error.
    """
    schema = QuestionStartedOption.model_json_schema()
    assert set(schema["properties"].keys()) == {"id", "body"}
    assert schema.get("additionalProperties") is False

    full_schema = QuestionStartedMessage.model_json_schema()
    declared_props = _collect_property_names(full_schema)
    assert "is_correct" not in declared_props
    assert "explanation" not in declared_props

    leaky_payload = {
        "type": "question.started",
        "payload": {
            "match_question_id": "1",
            "position": 1,
            "question": {
                "body": "Q?",
                "type": "single_choice",
                "options": [
                    {"id": "1", "body": "A", "is_correct": True},  # leak attempt
                ],
            },
            "started_at": "2026-05-10T10:00:00Z",
            "deadline_at": "2026-05-10T10:00:20Z",
            "server_now": "2026-05-10T10:00:00Z",
        },
    }
    with pytest.raises(Exception):
        QuestionStartedMessage.model_validate(leaky_payload)
