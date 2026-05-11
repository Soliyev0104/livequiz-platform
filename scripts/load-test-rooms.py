"""Async room/match load test for Phase 12 leaderboard measurements.

Run from the host with:

    pip install httpx httpx-ws
    python scripts/load-test-rooms.py --players 50 --questions 10

The script targets the Nginx dev port by default (http://localhost:8888),
creates a fresh published quiz, joins players over REST+WS, submits answers
as questions start, reads the live leaderboard, and writes:

    scripts/measurements/A_leaderboard.md
    scripts/measurements/A_leaderboard.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from httpx_ws import aconnect_ws


def pct(values: list[float], index: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[index]


def row(name: str, values: list[float]) -> str:
    return (
        f"| {name} | {len(values)} | {min(values, default=0):.1f} | "
        f"{pct(values, 49):.1f} | {pct(values, 94):.1f} | {max(values, default=0):.1f} |"
    )


def ws_absolute(base_url: str, relative_ws_url: str) -> str:
    base = urlparse(base_url)
    scheme = "wss" if base.scheme == "https" else "ws"
    joined = urljoin(base_url.rstrip("/") + "/", relative_ws_url.lstrip("/"))
    parsed = urlparse(joined)
    return urlunparse((scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


async def timed(coro) -> tuple[float, Any]:
    start = time.perf_counter()
    result = await coro
    return (time.perf_counter() - start) * 1000, result


async def login_host(client: httpx.AsyncClient, prefix: str) -> str:
    resp = await client.post(
        f"{prefix}/auth/login",
        json={"email": "host@livequiz.local", "password": "host"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def create_quiz(
    client: httpx.AsyncClient, prefix: str, token: str, questions: int
) -> tuple[str, list[int]]:
    headers = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        f"{prefix}/quiz-sets",
        headers=headers,
        json={"title": f"Load test {uuid.uuid4().hex[:8]}", "visibility": "public"},
    )
    create.raise_for_status()
    quiz_id = create.json()["id"]
    correct_ids: list[int] = []
    for pos in range(1, questions + 1):
        add = await client.post(
            f"{prefix}/quiz-sets/{quiz_id}/questions",
            headers=headers,
            json={
                "position": pos,
                "body": f"Load-test question {pos}",
                "type": "single_choice",
                "time_limit_seconds": 5,
                "points": 1000,
                "options": [
                    {"position": 1, "body": "A", "is_correct": True},
                    {"position": 2, "body": "B", "is_correct": False},
                    {"position": 3, "body": "C", "is_correct": False},
                ],
            },
        )
        add.raise_for_status()
        correct = next(o for o in add.json()["options"] if o["is_correct"])
        correct_ids.append(int(correct["id"]))
    publish = await client.post(f"{prefix}/quiz-sets/{quiz_id}/publish", headers=headers)
    publish.raise_for_status()
    return quiz_id, correct_ids


async def player_flow(
    idx: int,
    client: httpx.AsyncClient,
    base_url: str,
    prefix: str,
    code: str,
    correct_ids: list[int],
    ready_q: asyncio.Queue[int],
    start_evt: asyncio.Event,
    match_id_ref: dict[str, int],
    metrics: dict[str, list[float]],
) -> None:
    join_ms, join_resp = await timed(
        client.post(f"{prefix}/rooms/{code}/join", json={"nickname": f"p{idx:03d}"})
    )
    join_resp.raise_for_status()
    metrics["join_ms"].append(join_ms)
    token = join_resp.json()["participant_token"]
    ws_url = ws_absolute(base_url, join_resp.json()["ws_url"])

    async with aconnect_ws(ws_url, client=client) as ws:
        await ready_q.put(idx)
        await start_evt.wait()
        match_id = match_id_ref["match_id"]
        for expected_pos, correct_id in enumerate(correct_ids, start=1):
            question = None
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=12)
                if msg.get("type") == "question.started":
                    payload = msg["payload"]
                    if int(payload["position"]) == expected_pos:
                        question = payload
                        break
            if question is None:
                raise RuntimeError(f"player {idx} missed question {expected_pos}")

            answer_ms, answer = await timed(
                client.post(
                    f"{prefix}/matches/{match_id}/answers",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Request-ID": uuid.uuid4().hex,
                    },
                    json={
                        "match_question_id": question["match_question_id"],
                        "selected_option_ids": [str(correct_id)],
                    },
                )
            )
            answer.raise_for_status()
            metrics["answer_ms"].append(answer_ms)

            lb_ms, leaderboard = await timed(
                client.get(
                    f"{prefix}/matches/{match_id}/leaderboard",
                    headers={"Authorization": f"Bearer {token}"},
                )
            )
            leaderboard.raise_for_status()
            metrics["leaderboard_ms"].append(lb_ms)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    prefix = args.api_prefix.rstrip("/")
    metrics: dict[str, list[float]] = {
        "join_ms": [],
        "answer_ms": [],
        "leaderboard_ms": [],
    }
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        host_token = await login_host(client, prefix)
        quiz_id, correct_ids = await create_quiz(client, prefix, host_token, args.questions)
        headers = {"Authorization": f"Bearer {host_token}"}
        room = await client.post(
            f"{prefix}/rooms",
            headers=headers,
            json={"quiz_set_id": quiz_id, "max_players": max(args.players + 1, 2), "settings": {}},
        )
        room.raise_for_status()
        code = room.json()["code"]

        ready_q: asyncio.Queue[int] = asyncio.Queue()
        start_evt = asyncio.Event()
        match_id_ref: dict[str, int] = {}
        tasks = [
            asyncio.create_task(
                player_flow(
                    idx,
                    client,
                    args.base_url,
                    prefix,
                    code,
                    correct_ids,
                    ready_q,
                    start_evt,
                    match_id_ref,
                    metrics,
                )
            )
            for idx in range(args.players)
        ]
        for _ in range(args.players):
            await ready_q.get()

        start = await client.post(f"{prefix}/rooms/{code}/start", headers=headers)
        start.raise_for_status()
        match_id_ref["match_id"] = int(start.json()["match_id"])
        start_evt.set()
        await asyncio.gather(*tasks)
        end = await client.post(f"{prefix}/rooms/{code}/end", headers=headers)
        end.raise_for_status()

    return {
        "config": {
            "players": args.players,
            "questions": args.questions,
            "base_url": args.base_url,
            "api_prefix": prefix,
            "leaderboard_backend": os.getenv("LEADERBOARD_BACKEND", "redis"),
        },
        "metrics": metrics,
    }


def write_outputs(result: dict[str, Any]) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "scripts" / "measurements"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "A_leaderboard.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    metrics = result["metrics"]
    config = result["config"]
    md = [
        "# A. Leaderboard Load Test",
        "",
        "## Config",
        "",
        f"- players: {config['players']}",
        f"- questions: {config['questions']}",
        f"- base_url: {config['base_url']}",
        f"- api_prefix: {config['api_prefix']}",
        f"- observed LEADERBOARD_BACKEND: {config['leaderboard_backend']}",
        "",
        "## Results",
        "",
        "| metric | n | min_ms | p50_ms | p95_ms | max_ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        row("join_ms", metrics["join_ms"]),
        row("answer_ms", metrics["answer_ms"]),
        row("leaderboard_ms", metrics["leaderboard_ms"]),
        "",
        "## How to reproduce the before run",
        "",
        "Bring up api-a/api-b with `LEADERBOARD_BACKEND=pg`, restart the API "
        "containers so settings reload, rerun this script with the same "
        "arguments, then paste the second table alongside this one as "
        "`before (pg)` vs `after (redis)`.",
        "",
    ]
    (out_dir / "A_leaderboard.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:16]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=50)
    parser.add_argument("--questions", type=int, default=10)
    parser.add_argument("--base-url", default="http://localhost:8888")
    parser.add_argument("--api-prefix", default="/api/v1")
    return parser.parse_args()


if __name__ == "__main__":
    write_outputs(asyncio.run(run(parse_args())))
