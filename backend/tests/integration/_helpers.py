"""Plain helper functions shared by focused integration tests."""

from __future__ import annotations

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.ids import get_id_generator
from app.core.security import hash_password
from app.db.models.enums import UserRole
from app.db.models.match_question import MatchQuestion
from app.db.models.question import Question
from app.db.models.user import User


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(
    client: AsyncClient,
    email: str,
    password: str = "Password123!",
    display_name: str = "User",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def login_token(client: AsyncClient, email: str, password: str) -> str:
    return (await login(client, email, password))["access_token"]


async def make_user(
    engine,
    email: str,
    role: UserRole = UserRole.host,
    password: str = "HostPass123!",
) -> int:
    user_id = get_id_generator().next_id()
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                display_name=role.value.title(),
                role=role,
                is_active=True,
            )
        )
        await session.commit()
    return user_id


def single_choice_q(time_limit_seconds: int = 20) -> dict:
    return {
        "position": 1,
        "body": "What is 2+2?",
        "type": "single_choice",
        "time_limit_seconds": time_limit_seconds,
        "points": 1000,
        "options": [
            {"position": 1, "body": "3", "is_correct": False},
            {"position": 2, "body": "4", "is_correct": True},
        ],
    }


async def create_published_quiz(
    client: AsyncClient,
    token: str,
    *,
    time_limit_seconds: int = 20,
) -> tuple[str, list[dict]]:
    create = await client.post(
        "/api/v1/quiz-sets",
        headers=auth(token),
        json={"title": f"Quiz {uuid.uuid4().hex[:6]}", "visibility": "public"},
    )
    assert create.status_code == 201, create.text
    quiz_id = create.json()["id"]
    add_q = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/questions",
        headers=auth(token),
        json=single_choice_q(time_limit_seconds),
    )
    assert add_q.status_code == 201, add_q.text
    publish = await client.post(
        f"/api/v1/quiz-sets/{quiz_id}/publish", headers=auth(token)
    )
    assert publish.status_code == 200, publish.text
    return quiz_id, add_q.json()["options"]


async def create_room(
    client: AsyncClient,
    token: str,
    quiz_id: str,
    *,
    max_players: int = 50,
) -> dict:
    resp = await client.post(
        "/api/v1/rooms",
        headers=auth(token),
        json={"quiz_set_id": quiz_id, "max_players": max_players, "settings": {}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def join(client: AsyncClient, code: str, nickname: str) -> dict:
    resp = await client.post(f"/api/v1/rooms/{code}/join", json={"nickname": nickname})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def wait_for_question_armed(
    engine, match_id: int, position: int, timeout_s: float = 5.0
) -> MatchQuestion:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        async with sm() as session:
            stmt = select(MatchQuestion).where(
                MatchQuestion.match_id == match_id,
                MatchQuestion.position == position,
            )
            mq = (await session.execute(stmt)).scalar_one_or_none()
        if mq is not None and mq.started_at is not None:
            return mq
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("question did not arm before timeout")
        await asyncio.sleep(0.05)


async def setup_started_match(
    client: AsyncClient,
    engine,
    *,
    time_limit_seconds: int = 20,
    max_players: int = 50,
) -> dict:
    email = f"host-{uuid.uuid4().hex[:8]}@livequiz.local"
    await make_user(engine, email, UserRole.host)
    host_token = await login_token(client, email, "HostPass123!")
    quiz_id, options = await create_published_quiz(
        client, host_token, time_limit_seconds=max(5, time_limit_seconds)
    )
    if time_limit_seconds < 5:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session:
            stmt = select(Question).where(Question.quiz_set_id == int(quiz_id))
            question = (await session.execute(stmt)).scalar_one()
            question.time_limit_seconds = time_limit_seconds
            await session.commit()
    room = await create_room(client, host_token, quiz_id, max_players=max_players)
    player = await join(client, room["code"], "PlayerA")
    start = await client.post(
        f"/api/v1/rooms/{room['code']}/start", headers=auth(host_token)
    )
    assert start.status_code == 201, start.text
    match_id = int(start.json()["match_id"])
    mq = await wait_for_question_armed(engine, match_id, position=1)
    correct = next(int(o["id"]) for o in options if o["is_correct"])
    return {
        "host_token": host_token,
        "player_token": player["participant_token"],
        "room": room,
        "match_id": match_id,
        "match_question": mq,
        "correct_option_id": correct,
    }
