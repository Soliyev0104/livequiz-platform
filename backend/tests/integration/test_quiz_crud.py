"""Integration tests for the P04 quiz CRUD + publish API surface.

Reuses the testcontainer harness pattern from ``test_auth_flow.py``:
the ``app_client`` fixture wires a real Postgres + Redis under FastAPI's
ASGI transport and tears down with TRUNCATE + FLUSHDB so each test starts
with a deterministic blank slate.

The auth router only mints ROLE=player on register; tests that need a
host or admin insert that row directly through the engine, mirroring the
``test_users_endpoint_requires_admin`` precedent.
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
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)

    async with Redis(connection_pool=pool) as r:
        await r.flushdb()
        sha = await load_rate_limit_script(r)

    app = create_app()
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = sha

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
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
# Helpers
# ---------------------------------------------------------------------------


async def _register(
    client: AsyncClient, email: str, password: str = "Password123!"
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "U"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _make_host(
    migrated_engine, email: str, password: str = "HostPass123!"
) -> int:
    """Insert a User with ROLE=host directly via the engine; return id."""
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
    app_client: AsyncClient, migrated_engine, email: str = "host@quizcrud.example.com"
) -> tuple[int, str]:
    user_id = await _make_host(migrated_engine, email)
    tokens = await _login(app_client, email, "HostPass123!")
    return user_id, tokens["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _single_choice_q(position: int = 1, *, body: str = "Q?") -> dict:
    return {
        "position": position,
        "body": body,
        "type": "single_choice",
        "time_limit_seconds": 20,
        "points": 1000,
        "options": [
            {"position": 1, "body": "A", "is_correct": False},
            {"position": 2, "body": "B", "is_correct": True},
            {"position": 3, "body": "C", "is_correct": False},
        ],
    }


# ---------------------------------------------------------------------------
# Create + role guard
# ---------------------------------------------------------------------------


async def test_create_quiz_returns_201_and_summary(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)

    resp = await app_client.post(
        "/api/v1/quiz-sets",
        headers=_auth(token),
        json={
            "title": "Computer Networks Quiz",
            "description": "Subnetting, routing, DNS, HTTP",
            "visibility": "private",
            "tags": ["networks", "exam-prep"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Computer Networks Quiz"
    assert body["is_published"] is False
    assert body["version"] == 1
    assert body["question_count"] == 0
    assert isinstance(body["id"], str) and body["id"].isdigit()


async def test_create_quiz_requires_host_role(app_client: AsyncClient) -> None:
    # Public registration mints ROLE=player.
    await _register(app_client, "p@quizcrud.example.com", "Pass12345!")
    tokens = await _login(app_client, "p@quizcrud.example.com", "Pass12345!")

    resp = await app_client.post(
        "/api/v1/quiz-sets",
        headers=_auth(tokens["access_token"]),
        json={"title": "Banned", "tags": []},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def test_get_quiz_owner_sees_questions_and_anon_does_not_see_drafts(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, host_token = await _host_token(app_client, migrated_engine)

    create = await app_client.post(
        "/api/v1/quiz-sets",
        headers=_auth(host_token),
        json={"title": "Draft", "visibility": "private"},
    )
    quiz_id = create.json()["id"]

    await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(host_token),
        json=_single_choice_q(),
    )

    # Owner sees questions.
    owner_view = await app_client.get(
        f"/api/v1/quiz-sets/{quiz_id}", headers=_auth(host_token)
    )
    assert owner_view.status_code == 200
    body = owner_view.json()
    assert body["questions"] is not None
    assert len(body["questions"]) == 1
    assert body["questions"][0]["options"][1]["is_correct"] is True

    # Anonymous request -> private quiz is forbidden.
    anon = await app_client.get(f"/api/v1/quiz-sets/{quiz_id}")
    assert anon.status_code == 403
    assert anon.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def test_patch_quiz_increments_version(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)

    create = await app_client.post(
        "/api/v1/quiz-sets",
        headers=_auth(token),
        json={"title": "Old"},
    )
    quiz_id = create.json()["id"]
    assert create.json()["version"] == 1

    patch = await app_client.patch(
        f"/api/v1/quiz-sets/{quiz_id}",
        headers=_auth(token),
        json={"title": "New"},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["title"] == "New"
    assert body["version"] == 2


async def test_patch_quiz_non_owner_returns_403(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, host_token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets",
        headers=_auth(host_token),
        json={"title": "Mine"},
    )
    quiz_id = create.json()["id"]

    # Second host (different owner).
    _, other_token = await _host_token(
        app_client, migrated_engine, email="other@quizcrud.example.com"
    )

    resp = await app_client.patch(
        f"/api/v1/quiz-sets/{quiz_id}",
        headers=_auth(other_token),
        json={"title": "Hijack"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Question lifecycle
# ---------------------------------------------------------------------------


async def test_add_question_appends_when_position_omitted(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "Q"}
    )
    quiz_id = create.json()["id"]

    body_no_pos = {**_single_choice_q(), "position": None}
    r1 = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=body_no_pos,
    )
    r2 = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=body_no_pos,
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["position"] == 1
    assert r2.json()["position"] == 2


async def test_add_question_at_occupied_position_shifts_siblings(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "Shift"}
    )
    quiz_id = create.json()["id"]

    # Seed positions 1, 2, 3.
    for pos in (1, 2, 3):
        await app_client.post(
            f"/api/v1/quiz-sets/{quiz_id}/questions",
            headers=_auth(token),
            json=_single_choice_q(position=pos, body=f"Q{pos}"),
        )

    # Insert at position 2 — existing 2 and 3 should shift to 3 and 4.
    inserted = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=_single_choice_q(position=2, body="NEW"),
    )
    assert inserted.status_code == 201
    assert inserted.json()["position"] == 2

    detail = await app_client.get(
        f"/api/v1/quiz-sets/{quiz_id}", headers=_auth(token)
    )
    questions = detail.json()["questions"]
    by_position = {q["position"]: q["body"] for q in questions}
    assert by_position[1] == "Q1"
    assert by_position[2] == "NEW"
    assert by_position[3] == "Q2"
    assert by_position[4] == "Q3"


async def test_patch_question_replaces_options(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "PQ"}
    )
    quiz_id = create.json()["id"]
    qresp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=_single_choice_q(),
    )
    question_id = qresp.json()["id"]

    patched = await app_client.patch(
        f"/api/v1/questions/{question_id}",
        headers=_auth(token),
        json={
            "body": "Updated body",
            "options": [
                {"position": 1, "body": "Yes", "is_correct": True},
                {"position": 2, "body": "No", "is_correct": False},
            ],
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["body"] == "Updated body"
    assert len(body["options"]) == 2
    assert body["options"][0]["body"] == "Yes"
    assert body["options"][0]["is_correct"] is True


async def test_delete_question_renumbers_siblings(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "Del"}
    )
    quiz_id = create.json()["id"]

    ids: list[str] = []
    for pos in (1, 2, 3):
        r = await app_client.post(
            f"/api/v1/quiz-sets/{quiz_id}/questions",
            headers=_auth(token),
            json=_single_choice_q(position=pos, body=f"Q{pos}"),
        )
        ids.append(r.json()["id"])

    # Delete the middle one.
    resp = await app_client.delete(
        f"/api/v1/questions/{ids[1]}", headers=_auth(token)
    )
    assert resp.status_code == 204

    detail = await app_client.get(
        f"/api/v1/quiz-sets/{quiz_id}", headers=_auth(token)
    )
    by_pos = {q["position"]: q["body"] for q in detail.json()["questions"]}
    assert by_pos == {1: "Q1", 2: "Q3"}


# ---------------------------------------------------------------------------
# Publish validation
# ---------------------------------------------------------------------------


async def _create_quiz_with_question(
    app_client: AsyncClient, token: str, *, question_payload: dict
) -> str:
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "P"}
    )
    quiz_id = create.json()["id"]
    await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=_auth(token),
        json=question_payload,
    )
    return quiz_id


async def test_publish_empty_quiz_returns_422(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    create = await app_client.post(
        "/api/v1/quiz-sets", headers=_auth(token), json={"title": "E"}
    )
    quiz_id = create.json()["id"]

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    codes = {issue["code"] for issue in body["error"]["details"]["issues"]}
    assert "EMPTY_QUIZ" in codes


async def test_publish_single_choice_with_zero_correct_returns_422(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    bad = {
        "position": 1,
        "body": "?",
        "type": "single_choice",
        "options": [
            {"position": 1, "body": "A", "is_correct": False},
            {"position": 2, "body": "B", "is_correct": False},
        ],
    }
    quiz_id = await _create_quiz_with_question(
        app_client, token, question_payload=bad
    )

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 422
    codes = {
        issue["code"]
        for issue in resp.json()["error"]["details"]["issues"]
    }
    assert "EXPECTED_ONE_CORRECT" in codes


async def test_publish_multiple_choice_with_all_correct_returns_422(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    bad = {
        "position": 1,
        "body": "?",
        "type": "multiple_choice",
        "options": [
            {"position": 1, "body": "A", "is_correct": True},
            {"position": 2, "body": "B", "is_correct": True},
        ],
    }
    quiz_id = await _create_quiz_with_question(
        app_client, token, question_payload=bad
    )

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 422
    codes = {
        issue["code"]
        for issue in resp.json()["error"]["details"]["issues"]
    }
    assert "EXPECTED_SOME_NOT_ALL_CORRECT" in codes


async def test_publish_true_false_with_three_options_returns_422(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    bad = {
        "position": 1,
        "body": "?",
        "type": "true_false",
        "options": [
            {"position": 1, "body": "True", "is_correct": True},
            {"position": 2, "body": "False", "is_correct": False},
            {"position": 3, "body": "Maybe", "is_correct": False},
        ],
    }
    quiz_id = await _create_quiz_with_question(
        app_client, token, question_payload=bad
    )

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 422
    codes = {
        issue["code"]
        for issue in resp.json()["error"]["details"]["issues"]
    }
    assert "WRONG_TF_OPTION_COUNT" in codes


# ---------------------------------------------------------------------------
# Publish happy path + outbox
# ---------------------------------------------------------------------------


async def test_publish_happy_path_writes_outbox_row(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    quiz_id = await _create_quiz_with_question(
        app_client, token, question_payload=_single_choice_q()
    )

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_published"] is True
    assert body["version"] == 2

    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sm() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT event_type, aggregate_type, aggregate_id, "
                    "published_at FROM outbox_events WHERE aggregate_id=:id"
                ),
                {"id": int(quiz_id)},
            )
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "QuizPublished"
    assert rows[0][1] == "quiz_set"
    assert rows[0][2] == int(quiz_id)
    assert rows[0][3] is None  # not yet published to broker (P08 consumer absent)


async def test_publish_increments_version_and_sets_is_published(
    app_client: AsyncClient, migrated_engine
) -> None:
    _, token = await _host_token(app_client, migrated_engine)
    quiz_id = await _create_quiz_with_question(
        app_client, token, question_payload=_single_choice_q()
    )

    resp = await app_client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_published"] is True
    assert body["version"] == 2

    detail = await app_client.get(
        f"/api/v1/quiz-sets/{quiz_id}", headers=_auth(token)
    )
    assert detail.json()["is_published"] is True
    assert detail.json()["version"] == 2
