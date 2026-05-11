"""Match analytics service.

Read path (per docs/06):

1. Try Redis warm cache (``cache:analytics:match:{id}``). The stream
   worker populates this on ``MatchFinished``; an explicit refresh
   request bypasses with ``force_refresh=True``.
2. Query ClickHouse: ``question_accuracy_mv`` for per-question stats,
   ``answer_events`` for response-time quantiles. The MV writes a row
   per ingest so this is cheap even for long matches.
3. Postgres fallback when ClickHouse is unreachable — accuracy is
   computed straight from ``answer_submissions``. The API sets
   ``X-Source: postgres-fallback`` so a sustained CH outage is
   observable from the response headers.

Final leaderboard is always sourced from Postgres ``final_scores``;
the OLTP store is the source of truth for scoring, ClickHouse just
holds the post-match analytics shape.

The sync ``clickhouse-connect`` driver is wrapped in
``asyncio.to_thread`` so the event loop stays cooperative.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.answer_submission import AnswerSubmission
from app.db.models.final_score import FinalScore
from app.db.models.match_question import MatchQuestion
from app.db.models.room_participant import RoomParticipant


log = logging.getLogger("app.services.analytics")


CACHE_KEY_TMPL = "cache:analytics:match:{match_id}"
CACHE_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Source markers — set as X-Source response header by the router.
# ---------------------------------------------------------------------------


SOURCE_CACHE = "redis-cache"
SOURCE_CLICKHOUSE = "clickhouse"
SOURCE_POSTGRES = "postgres-fallback"


@dataclass(frozen=True)
class AnalyticsResult:
    body: dict[str, Any]
    source: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_match_analytics(
    *,
    session: AsyncSession,
    redis: Redis,
    match_id: int,
    use_cache: bool = True,
) -> AnalyticsResult:
    """Return the analytics payload for ``match_id``.

    Always includes the final leaderboard (from Postgres) regardless
    of where the rest of the payload originated. An empty match
    returns zeroed arrays — the UI must not crash on a quiet match.
    """
    if use_cache:
        cached = await _read_cache(redis, match_id)
        if cached is not None:
            cached["final_leaderboard"] = await _final_leaderboard_pg(
                session, match_id
            )
            return AnalyticsResult(body=cached, source=SOURCE_CACHE)

    settings = get_settings()
    ch_payload: dict[str, Any] | None = None
    try:
        ch_payload = await _query_clickhouse(
            settings.clickhouse_url, settings.clickhouse_db, match_id
        )
    except Exception as exc:  # noqa: BLE001 — fall through to Postgres
        log.warning("analytics: clickhouse unavailable match=%s: %s", match_id, exc)

    if ch_payload is None:
        body = await _query_postgres(session, match_id)
        body["final_leaderboard"] = await _final_leaderboard_pg(session, match_id)
        return AnalyticsResult(body=body, source=SOURCE_POSTGRES)

    ch_payload["final_leaderboard"] = await _final_leaderboard_pg(session, match_id)
    # Warm the cache for the next reader. Best-effort.
    try:
        await redis.set(
            CACHE_KEY_TMPL.format(match_id=match_id),
            json.dumps(ch_payload, separators=(",", ":")),
            ex=CACHE_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics: cache write failed match=%s: %s", match_id, exc)

    return AnalyticsResult(body=ch_payload, source=SOURCE_CLICKHOUSE)


# ---------------------------------------------------------------------------
# Redis cache
# ---------------------------------------------------------------------------


async def _read_cache(redis: Redis, match_id: int) -> dict[str, Any] | None:
    try:
        raw = await redis.get(CACHE_KEY_TMPL.format(match_id=match_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics: cache read failed match=%s: %s", match_id, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("analytics: cache poisoned match=%s", match_id)
        return None


# ---------------------------------------------------------------------------
# ClickHouse path
# ---------------------------------------------------------------------------


_QUESTION_ACCURACY_SQL = """
SELECT
    question_id,
    sum(total_answers)        AS total_answers,
    sum(correct_answers)      AS correct_answers,
    sum(response_time_sum_ms) AS rt_sum_ms
FROM livequiz.question_accuracy_mv
WHERE match_id = {match_id:UInt64}
GROUP BY question_id
ORDER BY question_id
"""

_RESPONSE_TIME_SQL = """
SELECT
    quantile(0.50)(response_time_ms) AS p50,
    quantile(0.95)(response_time_ms) AS p95,
    quantile(0.99)(response_time_ms) AS p99,
    avg(response_time_ms)            AS avg_ms,
    count()                          AS total
FROM livequiz.answer_events
WHERE match_id = {match_id:UInt64}
"""


async def _query_clickhouse(
    url: str, database: str, match_id: int
) -> dict[str, Any] | None:
    from clickhouse_connect import get_client

    def _go() -> dict[str, Any] | None:
        client = get_client(
            dsn=url,
            database=database,
            connect_timeout=2,
            send_receive_timeout=3,
        )
        try:
            acc_rows = client.query(
                _QUESTION_ACCURACY_SQL, parameters={"match_id": match_id}
            ).result_rows
            rt_rows = client.query(
                _RESPONSE_TIME_SQL, parameters={"match_id": match_id}
            ).result_rows
        finally:
            client.close()

        question_accuracy: list[dict[str, Any]] = []
        total_answers_all = 0
        for q_id, total, correct, rt_sum_ms in acc_rows or []:
            total_int = int(total or 0)
            correct_int = int(correct or 0)
            avg_ms = int((rt_sum_ms or 0) / total_int) if total_int else 0
            total_answers_all += total_int
            question_accuracy.append(
                {
                    "question_id": str(q_id),
                    "total_answers": total_int,
                    "correct_answers": correct_int,
                    "accuracy_percent": (
                        round(100.0 * correct_int / total_int, 1) if total_int else 0.0
                    ),
                    "avg_response_ms": avg_ms,
                }
            )

        if rt_rows:
            p50, p95, p99, avg_ms, total = rt_rows[0]
        else:
            p50 = p95 = p99 = avg_ms = total = 0

        most_missed = sorted(
            question_accuracy, key=lambda q: q["accuracy_percent"]
        )[:5]

        return {
            "match_id": str(match_id),
            "question_accuracy": question_accuracy,
            "response_time_distribution": {
                "p50_ms": int(p50 or 0),
                "p95_ms": int(p95 or 0),
                "p99_ms": int(p99 or 0),
                "avg_ms": int(avg_ms or 0),
            },
            "most_missed_questions": most_missed,
            "total_answers": int(total_answers_all or total or 0),
        }

    return await asyncio.to_thread(_go)


# ---------------------------------------------------------------------------
# Postgres fallback
# ---------------------------------------------------------------------------


async def _query_postgres(session: AsyncSession, match_id: int) -> dict[str, Any]:
    """Recompute the analytics body from OLTP rows.

    Honest fallback: ``question_accuracy`` joins ``answer_submissions``
    to ``match_questions``. The match-question count is small (≤ ~50)
    and answer rows are bounded by `participants × questions`, so a
    single match's analytics computes in a few ms even on stock
    hardware.
    """
    # Per-question aggregation
    per_q_stmt = (
        select(
            MatchQuestion.question_id.label("question_id"),
            func.count(AnswerSubmission.id).label("total"),
            func.sum(cast(AnswerSubmission.is_correct, Integer)).label("correct"),
            func.avg(AnswerSubmission.response_time_ms).label("avg_ms"),
        )
        .join(
            AnswerSubmission,
            AnswerSubmission.match_question_id == MatchQuestion.id,
            isouter=True,
        )
        .where(MatchQuestion.match_id == match_id)
        .group_by(MatchQuestion.question_id)
        .order_by(MatchQuestion.question_id)
    )
    rows = list((await session.execute(per_q_stmt)).all())

    question_accuracy: list[dict[str, Any]] = []
    total_answers = 0
    for question_id, total, correct, avg_ms in rows:
        total_int = int(total or 0)
        correct_int = int(correct or 0)
        total_answers += total_int
        question_accuracy.append(
            {
                "question_id": str(question_id),
                "total_answers": total_int,
                "correct_answers": correct_int,
                "accuracy_percent": (
                    round(100.0 * correct_int / total_int, 1) if total_int else 0.0
                ),
                "avg_response_ms": int(avg_ms or 0),
            }
        )

    # Response-time distribution via percentile_cont
    pct_stmt = select(
        func.percentile_cont(0.50)
        .within_group(AnswerSubmission.response_time_ms.asc())
        .label("p50"),
        func.percentile_cont(0.95)
        .within_group(AnswerSubmission.response_time_ms.asc())
        .label("p95"),
        func.percentile_cont(0.99)
        .within_group(AnswerSubmission.response_time_ms.asc())
        .label("p99"),
        func.avg(AnswerSubmission.response_time_ms).label("avg_ms"),
    ).where(AnswerSubmission.match_id == match_id)
    pct_row = (await session.execute(pct_stmt)).one_or_none()
    if pct_row is not None and any(
        v is not None for v in (pct_row.p50, pct_row.p95, pct_row.p99)
    ):
        p50, p95, p99, avg_ms = pct_row
    else:
        p50 = p95 = p99 = avg_ms = 0

    most_missed = sorted(
        question_accuracy, key=lambda q: q["accuracy_percent"]
    )[:5]

    return {
        "match_id": str(match_id),
        "question_accuracy": question_accuracy,
        "response_time_distribution": {
            "p50_ms": int(p50 or 0),
            "p95_ms": int(p95 or 0),
            "p99_ms": int(p99 or 0),
            "avg_ms": int(avg_ms or 0),
        },
        "most_missed_questions": most_missed,
        "total_answers": total_answers,
    }


# ---------------------------------------------------------------------------
# Final leaderboard (always Postgres)
# ---------------------------------------------------------------------------


async def _final_leaderboard_pg(
    session: AsyncSession, match_id: int
) -> list[dict[str, Any]]:
    stmt = (
        select(FinalScore, RoomParticipant.nickname)
        .join(
            RoomParticipant,
            RoomParticipant.id == FinalScore.participant_id,
            isouter=True,
        )
        .where(FinalScore.match_id == match_id)
        .order_by(FinalScore.rank.asc())
    )
    rows = list((await session.execute(stmt)).all())
    return [
        {
            "rank": fs.rank,
            "participant_id": str(fs.participant_id),
            "nickname": nickname or "",
            "total_score": int(fs.total_score),
            "correct_count": int(fs.correct_count),
            "average_response_ms": fs.average_response_ms,
        }
        for fs, nickname in rows
    ]
