"""Integration tests for the P07 answer submission transaction.

Covered scenarios (per docs/05 + docs/06):

1. ``test_submit_answer_writes_submission_and_outbox`` — the canonical
   happy path. Returns ``202``, persists an ``answer_submissions`` row,
   awards speed-bonus points, and writes an ``AnswerSubmitted`` outbox
   row in the same transaction.
2. ``test_duplicate_request_id_returns_identical_response`` — the same
   ``X-Request-ID`` retried produces the same response, with no second
   submission row.
3. ``test_second_answer_same_participant_question_resolves_idempotently``
   — a different ``X-Request-ID`` for the same (participant,
   match_question) pair hits ``ux_submission_once`` and falls back to
   the original row's response.
4. ``test_deadline_passed_returns_question_closed`` — submitting after
   the question's ``deadline_at + grace`` raises ``QUESTION_CLOSED``
   (409) and writes nothing.

Time control: the test quiz uses ``time_limit_seconds=2`` so the
deadline-passed test only sleeps ~2.5s. We poll for the
``started_at`` watermark on ``match_questions`` instead of sleeping a
fixed interval — the scheduler's first ``arm_question`` task fires on
the event loop after ``start_match`` returns.
"""

from __future__ import annotations

import asyncio
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
from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.answer_submission import AnswerSubmission
from app.db.models.enums import UserRole
from app.db.models.match_question import MatchQuestion
from app.db.models.outbox_event import OutboxEvent
from app.db.models.question import Question
from app.db.models.user import User
from app.main import create_app
from app.services import match_service

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    # The app's normal lifespan would build the ConnectionManager and
    # match_runtime; tests bypass lifespan to keep the testcontainer
    # plumbing simple, so wire those directly here.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_host(migrated_engine, email: str, password: str = "HostPass123!") -> int:
    from app.core.ids import get_id_generator

    user_id = get_id_generator().next_id()
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


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _create_published_quiz(
    client: AsyncClient,
    token: str,
    *,
    time_limit_seconds: int = 30,
) -> tuple[str, list[dict]]:
    """Create a public published quiz with a single deterministic question.

    Returns ``(quiz_id, options)`` where ``options`` mirrors the request
    so the test can pick the correct option_id by ``is_correct``.
    """
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
        json={
            "position": 1,
            "body": "What is 2+2?",
            "type": "single_choice",
            "time_limit_seconds": max(5, time_limit_seconds),
            "points": 1000,
            "options": [
                {"position": 1, "body": "3", "is_correct": False},
                {"position": 2, "body": "4", "is_correct": True},
                {"position": 3, "body": "5", "is_correct": False},
            ],
        },
    )
    assert add_q.status_code == 201, add_q.text

    publish = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=_auth(token)
    )
    assert publish.status_code == 200, publish.text
    return quiz_id, add_q.json()["options"]


async def _create_room(client: AsyncClient, token: str, quiz_id: str) -> dict:
    resp = await client.post(
        "/api/v1/rooms",
        headers=_auth(token),
        json={"quiz_set_id": quiz_id, "max_players": 10, "settings": {}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _join(client: AsyncClient, code: str, nickname: str) -> dict:
    resp = await client.post(
        f"/api/v1/rooms/{code}/join", json={"nickname": nickname}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wait_for_question_armed(
    migrated_engine, match_id: int, position: int, timeout_s: float = 5.0
) -> MatchQuestion:
    """Poll match_questions until ``started_at`` is set."""
    sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        async with sm() as s:
            stmt = select(MatchQuestion).where(
                MatchQuestion.match_id == match_id,
                MatchQuestion.position == position,
            )
            mq = (await s.execute(stmt)).scalar_one_or_none()
        if mq is not None and mq.started_at is not None:
            return mq
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"question position={position} never armed within {timeout_s}s"
            )
        await asyncio.sleep(0.05)


async def _setup_match(
    app_client: tuple[AsyncClient, ConnectionPool],
    migrated_engine,
    *,
    time_limit_seconds: int = 30,
) -> tuple[AsyncClient, str, str, MatchQuestion, int, int]:
    """Run the full host→start→player flow and return the bits the test
    cares about: ``(client, player_token, room_code, mq, match_id,
    correct_option_id)``.
    """
    client, _ = app_client
    host_email = f"host-{uuid.uuid4().hex[:6]}@a.test"
    await _make_host(migrated_engine, host_email)
    host_token = await _login(client, host_email, "HostPass123!")

    quiz_id, options = await _create_published_quiz(
        client, host_token, time_limit_seconds=time_limit_seconds
    )
    if time_limit_seconds < 5:
        sm = async_sessionmaker(migrated_engine, expire_on_commit=False)
        async with sm() as s:
            stmt = select(Question).where(Question.quiz_set_id == int(quiz_id))
            question = (await s.execute(stmt)).scalar_one()
            question.time_limit_seconds = time_limit_seconds
            await s.commit()
    correct_option_id = next(int(o["id"]) for o in options if o["is_correct"])

    room = await _create_room(client, host_token, quiz_id)
    code = room["code"]

    join_a = await _join(client, code, "PlayerA")
    player_token = join_a["participant_token"]

    start = await client.post(
        f"/api/v1/rooms/{code}/start", headers=_auth(host_token)
    )
    assert start.status_code == 201, start.text
    match_id = int(start.json()["match_id"])

    mq = await _wait_for_question_armed(migrated_engine, match_id, position=1)
    return client, player_token, code, mq, match_id, correct_option_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_submit_answer_writes_submission_and_outbox(
    app_client: tuple[AsyncClient, ConnectionPool], migrated_engine
) -> None:
    client, player_token, _, mq, match_id, correct = await _setup_match(
        app_client, migrated_engine, time_limit_seconds=30
    )

    request_id = uuid.uuid4().hex
    resp = await client.post(
        f"/api/v1/matches/{match_id}/answers",
        headers={**_auth(player_token), "X-Request-ID": request_id},
        json={
            "match_question_id": str(mq.id),
            "selected_option_ids": [str(correct)],
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["is_correct"] is True
    assert body["score_awarded"] > 0
    submission_id = body["submission_id"]
    assert isinstance(submission_id, str)

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
        outbox = list(
            (
                await s.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "AnswerSubmitted",
                        OutboxEvent.aggregate_id == int(submission_id),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].request_id == request_id
    assert rows[0].is_correct is True
    assert len(outbox) == 1
    assert outbox[0].payload["submission_id"] == submission_id


async def test_duplicate_request_id_returns_identical_response(
    app_client: tuple[AsyncClient, ConnectionPool], migrated_engine
) -> None:
    client, player_token, _, mq, match_id, correct = await _setup_match(
        app_client, migrated_engine, time_limit_seconds=30
    )

    request_id = uuid.uuid4().hex
    body = {
        "match_question_id": str(mq.id),
        "selected_option_ids": [str(correct)],
    }
    headers = {**_auth(player_token), "X-Request-ID": request_id}

    first = await client.post(
        f"/api/v1/matches/{match_id}/answers", headers=headers, json=body
    )
    assert first.status_code == 202
    second = await client.post(
        f"/api/v1/matches/{match_id}/answers", headers=headers, json=body
    )
    assert second.status_code == 202
    assert first.json()["submission_id"] == second.json()["submission_id"]

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
    assert len(rows) == 1


async def test_second_answer_same_participant_question_resolves_idempotently(
    app_client: tuple[AsyncClient, ConnectionPool], migrated_engine
) -> None:
    client, player_token, _, mq, match_id, correct = await _setup_match(
        app_client, migrated_engine, time_limit_seconds=30
    )

    options_resp = mq
    request_id_1 = uuid.uuid4().hex
    first = await client.post(
        f"/api/v1/matches/{match_id}/answers",
        headers={**_auth(player_token), "X-Request-ID": request_id_1},
        json={
            "match_question_id": str(options_resp.id),
            "selected_option_ids": [str(correct)],
        },
    )
    assert first.status_code == 202

    # Second submit with a DIFFERENT request_id but same (participant, mq).
    request_id_2 = uuid.uuid4().hex
    second = await client.post(
        f"/api/v1/matches/{match_id}/answers",
        headers={**_auth(player_token), "X-Request-ID": request_id_2},
        json={
            "match_question_id": str(options_resp.id),
            # Pick a wrong option to prove the original (correct) answer wins.
            "selected_option_ids": [],
        },
    )
    assert second.status_code == 202, second.text
    assert second.json()["submission_id"] == first.json()["submission_id"]
    assert second.json()["is_correct"] is True

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
    assert len(rows) == 1, "second submit must not create a new row"


async def test_deadline_passed_returns_question_closed(
    app_client: tuple[AsyncClient, ConnectionPool], migrated_engine
) -> None:
    client, player_token, _, mq, match_id, correct = await _setup_match(
        app_client, migrated_engine, time_limit_seconds=1
    )

    # Wait past the deadline + 200ms grace.
    await asyncio.sleep(1.6)

    resp = await client.post(
        f"/api/v1/matches/{match_id}/answers",
        headers={**_auth(player_token), "X-Request-ID": uuid.uuid4().hex},
        json={
            "match_question_id": str(mq.id),
            "selected_option_ids": [str(correct)],
        },
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "QUESTION_CLOSED"

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
    assert rows == []
