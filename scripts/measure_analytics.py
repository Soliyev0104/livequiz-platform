"""Measurement C — Postgres vs ClickHouse accuracy aggregation latency.

Seeds 10 000 synthetic answer rows into both Postgres
(``answer_submissions``) and ClickHouse (``answer_events``); runs the
per-question accuracy aggregation `_RUNS` times on each store; writes
a markdown report with min / p50 / p95 / p99 latency to
``scripts/measurements/C_analytics.md``.

Run inside the api-a container so DATABASE_URL and CLICKHOUSE_URL
resolve to the docker-compose hosts:

    docker compose exec api-a python scripts/measure_analytics.py
"""

from __future__ import annotations

import asyncio
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


_DATASET_SIZE = 10_000
_RUNS = 20
_BENCH_MATCH_ID = 999_000_000_000
_BENCH_ROOM_ID = 999_000_000_001
_BENCH_QUIZ_ID = 999_000_000_002
_BENCH_OWNER_ID = 999_000_000_003

# Spread answers across 20 questions, 50 participants — produces a
# realistic shape: every (match, question) has ~500 rows, so the
# aggregation isn't dominated by setup cost.
_QUESTION_COUNT = 20
_PARTICIPANT_COUNT = 50


PG_AGGREGATE_SQL = """
SELECT mq.question_id,
       count(asub.id) AS total,
       sum(CASE WHEN asub.is_correct THEN 1 ELSE 0 END) AS correct,
       avg(asub.response_time_ms) AS avg_ms
FROM match_questions mq
LEFT JOIN answer_submissions asub
  ON asub.match_question_id = mq.id
WHERE mq.match_id = :match_id
GROUP BY mq.question_id
ORDER BY mq.question_id
"""

CH_AGGREGATE_SQL = """
SELECT question_id,
       sum(total_answers) AS total,
       sum(correct_answers) AS correct,
       sum(response_time_sum_ms) AS rt_sum
FROM livequiz.question_accuracy_mv
WHERE match_id = {match_id:UInt64}
GROUP BY question_id
ORDER BY question_id
"""


@dataclass
class PhaseResult:
    name: str
    timings_ms: list[float]

    @property
    def stats(self) -> dict[str, float]:
        if not self.timings_ms:
            return {"min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        sorted_ms = sorted(self.timings_ms)
        n = len(sorted_ms)
        p50 = statistics.median(sorted_ms)
        p95 = sorted_ms[max(0, int(0.95 * (n - 1)))]
        p99 = sorted_ms[max(0, int(0.99 * (n - 1)))]
        return {
            "min": sorted_ms[0],
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "max": sorted_ms[-1],
        }


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


async def _seed_postgres(sm) -> tuple[list[int], list[int]]:
    """Insert fixture rows directly via SQL so we don't pull in the
    ORM lifecycle hooks. Returns (question_ids, mq_ids)."""

    rng = random.Random(1337)
    async with sm() as s:
        # Clean up prior run. asyncpg only runs one statement per
        # `.execute`, so each DELETE is its own call.
        cleanup_params = {
            "match_id": _BENCH_MATCH_ID,
            "room_id": _BENCH_ROOM_ID,
            "quiz_id": _BENCH_QUIZ_ID,
            "owner_id": _BENCH_OWNER_ID,
        }
        cleanup_stmts = [
            "DELETE FROM answer_submissions WHERE match_id = :match_id",
            "DELETE FROM match_questions WHERE match_id = :match_id",
            "DELETE FROM matches WHERE id = :match_id",
            "DELETE FROM room_participants WHERE room_id = :room_id",
            (
                "DELETE FROM answer_options WHERE question_id IN ("
                "SELECT id FROM questions WHERE quiz_set_id = :quiz_id)"
            ),
            "DELETE FROM questions WHERE quiz_set_id = :quiz_id",
            "DELETE FROM rooms WHERE id = :room_id",
            "DELETE FROM quiz_sets WHERE id = :quiz_id",
            "DELETE FROM users WHERE id = :owner_id",
        ]
        for stmt in cleanup_stmts:
            await s.execute(text(stmt), cleanup_params)

        await s.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, "
                "role, is_active) VALUES (:id, :email, 'x', 'Bench', 'host', TRUE)"
            ),
            {"id": _BENCH_OWNER_ID, "email": f"bench-{_BENCH_OWNER_ID}@livequiz.local"},
        )
        await s.execute(
            text(
                "INSERT INTO quiz_sets (id, owner_id, title, visibility, "
                "is_published, version) "
                "VALUES (:id, :owner_id, 'Bench Quiz', 'public', TRUE, 1)"
            ),
            {"id": _BENCH_QUIZ_ID, "owner_id": _BENCH_OWNER_ID},
        )
        await s.execute(
            text(
                "INSERT INTO rooms (id, code, host_id, quiz_set_id, status, "
                "max_players, settings) "
                "VALUES (:id, :code, :host_id, :quiz_id, 'completed', 200, '{}')"
            ),
            {
                "id": _BENCH_ROOM_ID,
                "code": "BENCH1",
                "host_id": _BENCH_OWNER_ID,
                "quiz_id": _BENCH_QUIZ_ID,
            },
        )
        await s.execute(
            text(
                "INSERT INTO matches (id, room_id, quiz_set_version, status) "
                "VALUES (:id, :room_id, 1, 'completed')"
            ),
            {"id": _BENCH_MATCH_ID, "room_id": _BENCH_ROOM_ID},
        )

        # Questions + match_questions
        question_ids: list[int] = []
        mq_ids: list[int] = []
        for i in range(_QUESTION_COUNT):
            qid = _BENCH_QUIZ_ID + 100 + i
            mqid = _BENCH_MATCH_ID + 100 + i
            question_ids.append(qid)
            mq_ids.append(mqid)
            await s.execute(
                text(
                    "INSERT INTO questions (id, quiz_set_id, position, body, "
                    "type, time_limit_seconds, points) "
                    "VALUES (:id, :quiz_id, :pos, :body, 'single_choice', 20, 1000)"
                ),
                {
                    "id": qid,
                    "quiz_id": _BENCH_QUIZ_ID,
                    "pos": i + 1,
                    "body": f"Q{i+1}",
                },
            )
            await s.execute(
                text(
                    "INSERT INTO match_questions (id, match_id, question_id, "
                    "position) VALUES (:id, :match_id, :qid, :pos)"
                ),
                {
                    "id": mqid,
                    "match_id": _BENCH_MATCH_ID,
                    "qid": qid,
                    "pos": i + 1,
                },
            )

        # Participants
        participant_ids: list[int] = []
        for i in range(_PARTICIPANT_COUNT):
            pid = _BENCH_ROOM_ID + 10_000 + i
            participant_ids.append(pid)
            await s.execute(
                text(
                    "INSERT INTO room_participants (id, room_id, nickname) "
                    "VALUES (:id, :room_id, :nick)"
                ),
                {"id": pid, "room_id": _BENCH_ROOM_ID, "nick": f"p{i}"},
            )

        # Answer submissions — exactly _DATASET_SIZE rows.
        rows: list[dict] = []
        for n in range(_DATASET_SIZE):
            mq = rng.choice(list(zip(mq_ids, question_ids)))
            participant = rng.choice(participant_ids)
            rows.append(
                {
                    "id": _BENCH_MATCH_ID + 10_000_000 + n,
                    "match_id": _BENCH_MATCH_ID,
                    "mq_id": mq[0],
                    "pid": participant,
                    "correct": rng.random() < 0.55,
                    "score": rng.randint(0, 1000),
                    "rt": rng.randint(200, 19_000),
                    "rid": f"bench-{n}",
                }
            )
        chunk = 500
        for i in range(0, len(rows), chunk):
            batch = rows[i : i + chunk]
            await s.execute(
                text(
                    "INSERT INTO answer_submissions (id, match_id, "
                    "match_question_id, participant_id, selected_option_ids, "
                    "is_correct, score_awarded, response_time_ms, request_id) "
                    "VALUES (:id, :match_id, :mq_id, :pid, ARRAY[]::bigint[], "
                    ":correct, :score, :rt, :rid)"
                ),
                batch,
            )
        await s.execute(text("ANALYZE answer_submissions"))
        await s.execute(text("ANALYZE match_questions"))
        await s.commit()
    return question_ids, mq_ids


def _seed_clickhouse(question_ids: list[int]) -> None:
    """Mirror _DATASET_SIZE rows into ClickHouse ``answer_events``.

    The materialised view pre-aggregates per-question so the query
    benches the SummingMergeTree merge path the API uses in prod.
    """
    from clickhouse_connect import get_client

    ch_url = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    ch_db = os.environ.get("CLICKHOUSE_DB", "livequiz")
    client = get_client(dsn=ch_url, database=ch_db)
    try:
        client.command(
            "ALTER TABLE livequiz.answer_events DELETE WHERE match_id = %(m)s",
            parameters={"m": _BENCH_MATCH_ID},
        )
        client.command(
            "ALTER TABLE livequiz.question_accuracy_mv DELETE WHERE match_id = %(m)s",
            parameters={"m": _BENCH_MATCH_ID},
        )

        rng = random.Random(1337)
        base_ts = datetime.now(tz=timezone.utc)
        rows = []
        for n in range(_DATASET_SIZE):
            q_id = rng.choice(question_ids)
            participant_id = _BENCH_ROOM_ID + 10_000 + rng.randint(0, _PARTICIPANT_COUNT - 1)
            rows.append(
                [
                    _BENCH_MATCH_ID + 10_000_000 + n,        # event_id
                    _BENCH_MATCH_ID,                          # match_id
                    _BENCH_ROOM_ID,                           # room_id
                    participant_id,                           # participant_id
                    q_id,                                     # question_id
                    1 if rng.random() < 0.55 else 0,          # is_correct
                    rng.randint(0, 1000),                     # score_awarded
                    rng.randint(200, 19_000),                 # response_time_ms
                    base_ts + timedelta(milliseconds=n),      # occurred_at
                ]
            )
        client.insert(
            "livequiz.answer_events",
            rows,
            column_names=[
                "event_id",
                "match_id",
                "room_id",
                "participant_id",
                "question_id",
                "is_correct",
                "score_awarded",
                "response_time_ms",
                "occurred_at",
            ],
        )
        # Encourage the MV to settle on disk so reads in the next
        # phase reflect merged state.
        client.command("OPTIMIZE TABLE livequiz.answer_events FINAL")
        client.command("OPTIMIZE TABLE livequiz.question_accuracy_mv FINAL")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------


async def _bench_postgres(sm) -> PhaseResult:
    timings: list[float] = []
    async with sm() as s:
        # Warm the buffer cache so the first run isn't an outlier.
        await s.execute(text(PG_AGGREGATE_SQL), {"match_id": _BENCH_MATCH_ID})
        for _ in range(_RUNS):
            t0 = time.perf_counter()
            await s.execute(text(PG_AGGREGATE_SQL), {"match_id": _BENCH_MATCH_ID})
            timings.append((time.perf_counter() - t0) * 1000.0)
    return PhaseResult(name="postgres", timings_ms=timings)


def _bench_clickhouse() -> PhaseResult:
    from clickhouse_connect import get_client

    ch_url = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
    ch_db = os.environ.get("CLICKHOUSE_DB", "livequiz")
    client = get_client(dsn=ch_url, database=ch_db)
    timings: list[float] = []
    try:
        # Warm-up
        client.query(CH_AGGREGATE_SQL, parameters={"match_id": _BENCH_MATCH_ID})
        for _ in range(_RUNS):
            t0 = time.perf_counter()
            client.query(CH_AGGREGATE_SQL, parameters={"match_id": _BENCH_MATCH_ID})
            timings.append((time.perf_counter() - t0) * 1000.0)
    finally:
        client.close()
    return PhaseResult(name="clickhouse", timings_ms=timings)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _format_report(pg: PhaseResult, ch: PhaseResult) -> str:
    ps = pg.stats
    cs = ch.stats
    lines: list[str] = []
    lines.append("# Measurement C — Match analytics: Postgres vs ClickHouse\n")
    lines.append(
        f"Dataset: **{_DATASET_SIZE}** synthetic answer rows for one match"
        f" across {_QUESTION_COUNT} questions and {_PARTICIPANT_COUNT} participants. "
        f"Each store ran the per-question accuracy aggregation **{_RUNS}** times.\n"
    )
    lines.append("## Per-question accuracy aggregation\n")
    lines.append("Postgres:\n\n```sql\n" + PG_AGGREGATE_SQL.strip() + "\n```\n")
    lines.append(
        "ClickHouse (uses pre-aggregated MV `question_accuracy_mv`):\n\n"
        "```sql\n" + CH_AGGREGATE_SQL.strip() + "\n```\n"
    )
    lines.append("## Timings (ms, lower is better)\n")
    lines.append(
        "| Store | min | p50 | p95 | p99 | max |\n|---|---:|---:|---:|---:|---:|"
    )
    lines.append(
        f"| postgres | {ps['min']:.3f} | {ps['p50']:.3f} | "
        f"{ps['p95']:.3f} | {ps['p99']:.3f} | {ps['max']:.3f} |"
    )
    lines.append(
        f"| clickhouse | {cs['min']:.3f} | {cs['p50']:.3f} | "
        f"{cs['p95']:.3f} | {cs['p99']:.3f} | {cs['max']:.3f} |"
    )
    if ps["p50"] > 0 and cs["p50"] > 0:
        ratio = ps["p50"] / cs["p50"]
        lines.append(f"\nClickHouse is **~{ratio:.1f}×** faster at p50.\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set; run inside api-a container.", file=sys.stderr)
        return 2

    engine = create_async_engine(db_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        question_ids, _ = await _seed_postgres(sm)
        try:
            await asyncio.to_thread(_seed_clickhouse, question_ids)
            ch_result = await asyncio.to_thread(_bench_clickhouse)
        except Exception as exc:  # noqa: BLE001
            print(
                f"ClickHouse bench unavailable: {exc}; reporting Postgres only.",
                file=sys.stderr,
            )
            ch_result = PhaseResult(name="clickhouse", timings_ms=[])

        pg_result = await _bench_postgres(sm)
        report = _format_report(pg_result, ch_result)
        out_path = (
            Path(__file__).resolve().parent / "measurements" / "C_analytics.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
