"""Match-aggregate events.

On ``MatchFinished`` we additionally pre-compute and warm the analytics
cache key the API reads. This is the only handler that runs a CH query
inline — the rest just append. The cache warming is best-effort: a
write failure logs but does not block offset commit, because the API
falls back to recomputing on cache miss.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.clickhouse_client import ClickHouseClient
from app.envelope import Envelope
from app.handlers._common import (
    EVENTS_RAW_COLUMNS,
    EVENTS_RAW_TABLE,
    _opt_int,
    envelope_to_raw_row,
)


log = logging.getLogger("stream-worker.handlers.match")


CACHE_KEY_TMPL = "cache:analytics:match:{match_id}"
CACHE_TTL_SECONDS = 3600  # 1h — long enough that a refresh on the
# results page is cheap, short enough that a backfill correction
# eventually propagates.


async def handle(env: Envelope, ch: ClickHouseClient, redis: Redis) -> None:
    await ch.insert_many(
        EVENTS_RAW_TABLE, [envelope_to_raw_row(env)], EVENTS_RAW_COLUMNS
    )

    if env.event_type != "MatchFinished":
        return

    match_id = _opt_int(env.payload.get("match_id")) or env.aggregate_id
    try:
        snapshot = await _compute_snapshot(ch, match_id)
    except Exception as exc:  # noqa: BLE001 — warm-cache must not block commit
        log.warning("match.snapshot_failed match=%s: %s", match_id, exc)
        return

    try:
        await redis.set(
            CACHE_KEY_TMPL.format(match_id=match_id),
            json.dumps(snapshot, separators=(",", ":")),
            ex=CACHE_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("match.cache_write_failed match=%s: %s", match_id, exc)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _compute_snapshot(ch: ClickHouseClient, match_id: int) -> dict[str, Any]:
    """Build the analytics snapshot for ``match_id`` from ClickHouse.

    Flushes any pending answer rows first so the snapshot reflects the
    full match — a MatchFinished can arrive within the same poll batch
    as the last AnswerSubmitted.
    """
    await ch.flush_all()

    accuracy_q = """
        SELECT question_id,
               count() AS total,
               sum(is_correct) AS correct,
               avg(response_time_ms) AS avg_ms,
               quantile(0.50)(response_time_ms) AS p50_ms,
               quantile(0.95)(response_time_ms) AS p95_ms
        FROM livequiz.answer_events
        WHERE match_id = {match_id:UInt64}
        GROUP BY question_id
        ORDER BY question_id
    """
    rows = await ch.query(accuracy_q, parameters={"match_id": match_id})
    raw_rows = rows.result_rows or []

    question_accuracy: list[dict[str, Any]] = []
    total_answers = 0
    for question_id, total, correct, avg_ms, p50_ms, p95_ms in raw_rows:
        total_int = int(total or 0)
        correct_int = int(correct or 0)
        total_answers += total_int
        accuracy_pct = round(100.0 * correct_int / total_int, 1) if total_int else 0.0
        question_accuracy.append(
            {
                "question_id": str(question_id),
                "total_answers": total_int,
                "correct_answers": correct_int,
                "accuracy_percent": accuracy_pct,
                "avg_response_ms": int(avg_ms or 0),
                "p50_response_ms": int(p50_ms or 0),
                "p95_response_ms": int(p95_ms or 0),
            }
        )

    rtd_q = """
        SELECT
            quantile(0.50)(response_time_ms) AS p50,
            quantile(0.95)(response_time_ms) AS p95,
            quantile(0.99)(response_time_ms) AS p99,
            avg(response_time_ms) AS avg
        FROM livequiz.answer_events
        WHERE match_id = {match_id:UInt64}
    """
    rtd_rows = (await ch.query(rtd_q, parameters={"match_id": match_id})).result_rows or [
        (0, 0, 0, 0)
    ]
    p50, p95, p99, avg_ms = rtd_rows[0]

    most_missed = sorted(
        question_accuracy, key=lambda q: q["accuracy_percent"]
    )[:5]

    final_leaderboard = env_payload_leaderboard(match_id)
    return {
        "match_id": str(match_id),
        "final_leaderboard": final_leaderboard,
        "question_accuracy": question_accuracy,
        "response_time_distribution": {
            "p50_ms": int(p50 or 0),
            "p95_ms": int(p95 or 0),
            "p99_ms": int(p99 or 0),
            "avg_ms": int(avg_ms or 0),
        },
        "most_missed_questions": most_missed,
        "total_answers": total_answers,
        "source": "clickhouse",
    }


def env_payload_leaderboard(_match_id: int) -> list[dict[str, Any]]:
    """Stub: final leaderboard is sourced by the API from Postgres.

    The warm cache only seeds the question-level stats — leaderboards
    live in the OLTP store and the API joins them in. Keeping that
    split means the worker stays decoupled from the Postgres schema.
    """
    return []
