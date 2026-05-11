"""Match lifecycle + answer submission service (P07).

Surfaces:

- :func:`start_match` — host transitions a lobby to a running match.
  Locks the room ``FOR UPDATE``, snapshots the quiz set's questions
  into ``match_questions``, registers ``MatchStarted`` in the outbox,
  COMMITs, then post-commit broadcasts ``match.started`` and schedules
  the first question arm.

- :func:`pause_match` / :func:`resume_match` — host control. Pause
  cancels the active deadline task and stashes the remaining time in
  Redis; resume re-arms a fresh ``close_question`` timer with
  ``deadline_at = now + remaining_ms``.

- :func:`end_match` — host or the auto-finish path from
  :func:`close_question`. Aggregates ``final_scores`` from
  ``answer_submissions``, breaks ties by ``average_response_ms`` ASC,
  registers ``MatchFinished`` in the outbox, and broadcasts the
  finish event.

- :func:`submit_answer` — the canonical doc/05 transaction:
  Redis idempotency probe → ``FOR UPDATE`` deadline check → INSERT
  submission (idempotent on unique violation) → INSERT outbox →
  COMMIT → post-commit Redis ZADD + WS broadcast + idem cache.

- :func:`arm_question` / :func:`close_question` — scheduler-driven.
  ``MatchScheduler`` keeps the active ``close_question`` task per
  match so :func:`pause_match` can cancel it.

- :func:`recover_running_matches` — startup-time crash recovery.

Runtime model: a single in-process :class:`MatchScheduler` owns the
asyncio Tasks. The README notes this is acceptable for the demo's
~50-match ceiling; production would dedicate a scheduler service.

Server time is authoritative everywhere — ``started_at`` and
``deadline_at`` come from the DB-side ``timezone.utc`` clock, not the
client. A 200 ms grace is added to the submit deadline check to absorb
network jitter on last-instant submissions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.cache import idempotency as idem_cache
from app.cache import leaderboard as lb_cache
from app.cache.keys import match_current_question
from app.cache.redis import RoomSnapshotWriter
from app.core import metrics as app_metrics
from app.core.config import get_settings
from app.core.ids import get_id_generator
from app.core.security import AuthError
from app.core.telemetry import span as otel_span
from app.db.models.answer_option import AnswerOption
from app.db.models.answer_submission import AnswerSubmission
from app.db.models.enums import RoomStatus
from app.db.models.final_score import FinalScore
from app.db.models.match import Match
from app.db.models.match_question import MatchQuestion
from app.db.models.question import Question
from app.db.models.quiz_set import QuizSet
from app.db.models.room import Room
from app.db.models.room_participant import RoomParticipant
from app.events.types import (
    AGG_ANSWER,
    AGG_MATCH,
    EVT_ANSWER_SUBMITTED,
    EVT_MATCH_FINISHED,
    EVT_MATCH_STARTED,
    EVT_QUESTION_CLOSED,
    EVT_QUESTION_STARTED,
)
from app.repositories.match_repo import MatchRepo
from app.schemas.match import AnswerSubmitRequest
from app.services import scoring_service
from app.services.outbox_service import register_event
from app.ws.connection_manager import ConnectionManager

log = logging.getLogger("app.services.match")


DEFAULT_INTER_QUESTION_SECONDS = 3
DEADLINE_GRACE_MS = 200


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@dataclass
class MatchRuntime:
    """Per-match runtime context shared with the scheduler tasks.

    Held on ``app.state.match_runtime`` so the API router and the
    scheduler tasks both pick up the same sessionmaker / pool / manager.
    Scheduler tasks cannot reuse a request-scoped ``AsyncSession``
    because the request has already returned by the time the task fires.
    """

    sessionmaker: async_sessionmaker
    redis_pool: ConnectionPool
    connection_manager: ConnectionManager
    capacity_admit_sha: str
    capacity_release_sha: str
    leaderboard_sha: str | None = None
    inter_question_seconds: int = DEFAULT_INTER_QUESTION_SECONDS


class MatchScheduler:
    """In-process registry of active deadline tasks, keyed by match_id.

    A single ``close_question`` task is active per match at any moment.
    ``pause_match`` cancels it; ``resume_match`` schedules a fresh one.
    The scheduler is a thin wrapper around an asyncio dict — it does
    not own any business logic.
    """

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[Any]] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def set_active(self, match_id: int, task: asyncio.Task[Any]) -> None:
        async with self._get_lock():
            old = self._tasks.pop(match_id, None)
            self._tasks[match_id] = task
            if old is not None and not old.done():
                old.cancel()

    async def cancel(self, match_id: int) -> bool:
        """Cancel the active task for ``match_id``. Returns True if one was running."""
        async with self._get_lock():
            task = self._tasks.pop(match_id, None)
        if task is None:
            return False
        if not task.done():
            task.cancel()
        return True

    async def cancel_all(self) -> None:
        async with self._get_lock():
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for t in tasks:
            if not t.done():
                t.cancel()


def get_scheduler(app_state: Any) -> MatchScheduler:
    sched = getattr(app_state, "match_scheduler", None)
    if sched is None:
        sched = MatchScheduler()
        app_state.match_scheduler = sched
    return sched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _broadcast(
    runtime: MatchRuntime, room_code: str, message: dict[str, Any]
) -> None:
    """Send ``message`` to every replica's clients for ``room_code``.

    A failure here must never roll back a Postgres commit — the durable
    answer/match transition is already on disk. We log and continue.
    """
    redis = Redis(connection_pool=runtime.redis_pool)
    try:
        await runtime.connection_manager.broadcast_all(redis, room_code, message)
    except Exception as exc:  # noqa: BLE001 — best-effort fan-out
        log.warning("broadcast failed room=%s type=%s: %s", room_code, message.get("type"), exc)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


async def _next_message_id() -> str:
    return str(get_id_generator().next_id())


async def _redis(runtime: MatchRuntime) -> Redis:
    return Redis(connection_pool=runtime.redis_pool)


# ---------------------------------------------------------------------------
# start_match
# ---------------------------------------------------------------------------


async def start_match(
    session: AsyncSession,
    runtime: MatchRuntime,
    *,
    host_id: int,
    room_code: str,
) -> Match:
    """Transition a lobby to ``running``.

    Locks the room ``FOR UPDATE`` so a concurrent host action (or a
    second replica racing the same code) cannot create two matches.
    The quiz_set version is captured at start time and copied to
    ``matches.quiz_set_version`` so subsequent quiz edits do not
    influence this match.
    """
    # 1. Lock room
    stmt = (
        select(Room)
        .where(Room.code == room_code)
        .with_for_update()
    )
    room = (await session.execute(stmt)).scalar_one_or_none()
    if room is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="room code not found")
    if room.host_id != host_id:
        raise AuthError("FORBIDDEN", 403, message="not the room host")
    if room.status != RoomStatus.lobby:
        raise AuthError(
            "ROOM_NOT_JOINABLE",
            409,
            message="match already started or completed",
            details={"status": room.status.value},
        )

    # 2. Snapshot quiz_set with questions (ordered)
    quiz_stmt = (
        select(QuizSet)
        .where(QuizSet.id == room.quiz_set_id)
        .options(selectinload(QuizSet.questions).selectinload(Question.options))
    )
    quiz = (await session.execute(quiz_stmt)).scalar_one_or_none()
    if quiz is None or not quiz.questions:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="quiz has no questions",
            details={"quiz_set_id": str(room.quiz_set_id)},
        )

    # 3. Insert match + match_questions
    gen = get_id_generator()
    started_at = _utcnow()
    match = Match(
        id=gen.next_id(),
        room_id=room.id,
        quiz_set_version=quiz.version,
        status=RoomStatus.running,
        started_at=started_at,
    )
    session.add(match)
    await session.flush()

    questions_sorted = sorted(quiz.questions, key=lambda q: q.position)
    match_questions: list[MatchQuestion] = []
    for idx, q in enumerate(questions_sorted, start=1):
        mq = MatchQuestion(
            id=gen.next_id(),
            match_id=match.id,
            question_id=q.id,
            position=idx,
            started_at=None,
            deadline_at=None,
            closed_at=None,
        )
        session.add(mq)
        match_questions.append(mq)
    await session.flush()

    # 4. Update room status + started_at
    room.status = RoomStatus.running
    room.started_at = started_at

    # 5. Outbox MatchStarted
    payload = {
        "match_id": str(match.id),
        "room_id": str(room.id),
        "code": room.code,
        "quiz_set_id": str(quiz.id),
        "quiz_set_version": quiz.version,
        "question_count": len(match_questions),
        "started_at": _iso(started_at),
    }
    await register_event(
        session,
        event_type=EVT_MATCH_STARTED,
        aggregate_type=AGG_MATCH,
        aggregate_id=match.id,
        payload=payload,
        occurred_at=started_at,
    )

    await session.commit()

    # 6. Post-commit: seed Redis match-state + broadcast match.started
    redis = await _redis(runtime)
    try:
        # Cache participant nicknames for leaderboard rendering
        part_stmt = select(RoomParticipant).where(
            RoomParticipant.room_id == room.id,
            RoomParticipant.left_at.is_(None),
            RoomParticipant.is_kicked.is_(False),
        )
        parts = list((await session.execute(part_stmt)).scalars().all())
        if parts:
            await lb_cache.set_nicknames(
                redis, match.id, [(p.id, p.nickname) for p in parts]
            )
        # Reset leaderboard ZSET (idempotent on retries)
        await lb_cache.reset(redis, match.id)
        # Update room snapshot status
        writer = RoomSnapshotWriter(
            redis,
            admit_sha=runtime.capacity_admit_sha,
            release_sha=runtime.capacity_release_sha,
        )
        cached = await writer.read(room.code)
        if cached is not None:
            cached.setdefault("room", {})["status"] = RoomStatus.running.value
            cached["match"] = {
                "match_id": str(match.id),
                "question_count": len(match_questions),
                "status": RoomStatus.running.value,
            }
            await writer.write(room.code, cached, status=RoomStatus.running)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass

    await _broadcast(
        runtime,
        room.code,
        {
            "type": "match.started",
            "message_id": await _next_message_id(),
            "payload": {
                "match_id": str(match.id),
                "question_count": len(match_questions),
                "server_now": _iso(_utcnow()),
            },
        },
    )

    # 7. Schedule the first question
    runtime_state_for(match.id, runtime)  # ensure runtime is registered
    asyncio.create_task(
        arm_question(runtime, match_id=match.id, position=1),
        name=f"match-arm-{match.id}-1",
    )
    return match


# ---------------------------------------------------------------------------
# arm_question
# ---------------------------------------------------------------------------


# Keep runtime keyed by match_id for the recovery path.
_runtime_by_match: dict[int, MatchRuntime] = {}


def runtime_state_for(match_id: int, runtime: MatchRuntime) -> None:
    _runtime_by_match[match_id] = runtime


def get_runtime_for(match_id: int) -> MatchRuntime | None:
    return _runtime_by_match.get(match_id)


async def arm_question(
    runtime: MatchRuntime, *, match_id: int, position: int
) -> None:
    """Set ``started_at``/``deadline_at`` for question at ``position`` and broadcast.

    Schedules a ``close_question`` task at the deadline. The Redis
    snapshot ``match:{id}:current_question`` is rewritten so a
    reconnecting client can recover the active question without
    waiting for the next event.
    """
    runtime_state_for(match_id, runtime)
    sm = runtime.sessionmaker
    room_code: str | None = None
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    question_payload: dict[str, Any] | None = None

    async with sm() as session:
        try:
            async with session.begin():
                mq_stmt = (
                    select(MatchQuestion)
                    .where(
                        MatchQuestion.match_id == match_id,
                        MatchQuestion.position == position,
                    )
                    .with_for_update()
                )
                mq = (await session.execute(mq_stmt)).scalar_one_or_none()
                if mq is None:
                    log.warning("arm_question: mq not found match=%s pos=%s", match_id, position)
                    return
                if mq.closed_at is not None:
                    log.info(
                        "arm_question: already closed match=%s pos=%s — skip",
                        match_id, position,
                    )
                    return

                match = await session.get(Match, match_id)
                if match is None or match.status != RoomStatus.running:
                    log.info(
                        "arm_question: match not running match=%s status=%s — skip",
                        match_id, match.status if match else "missing",
                    )
                    return

                question = await session.get(Question, mq.question_id)
                if question is None:
                    log.warning("arm_question: question missing %s", mq.question_id)
                    return
                opts_stmt = (
                    select(AnswerOption)
                    .where(AnswerOption.question_id == mq.question_id)
                    .order_by(AnswerOption.position.asc())
                )
                options = list((await session.execute(opts_stmt)).scalars().all())

                room = await session.get(Room, match.room_id)
                if room is None:
                    log.warning("arm_question: room missing for match %s", match_id)
                    return

                started_at = _utcnow()
                deadline_at = started_at + timedelta(
                    seconds=int(question.time_limit_seconds)
                )
                mq.started_at = started_at
                mq.deadline_at = deadline_at

                await register_event(
                    session,
                    event_type=EVT_QUESTION_STARTED,
                    aggregate_type=AGG_MATCH,
                    aggregate_id=match_id,
                    payload={
                        "match_id": str(match_id),
                        "match_question_id": str(mq.id),
                        "question_id": str(question.id),
                        "position": position,
                        "time_limit_seconds": int(question.time_limit_seconds),
                        "started_at": _iso(started_at),
                        "deadline_at": _iso(deadline_at),
                    },
                    occurred_at=started_at,
                )

                room_code = room.code
                question_payload = {
                    "match_question_id": str(mq.id),
                    "position": position,
                    "question": {
                        "body": question.body,
                        "type": question.type.value,
                        "options": [
                            {"id": str(o.id), "body": o.body} for o in options
                        ],
                    },
                    "started_at": _iso(started_at),
                    "deadline_at": _iso(deadline_at),
                    "server_now": _iso(_utcnow()),
                }
        except Exception:
            log.exception("arm_question failed match=%s pos=%s", match_id, position)
            return

    if question_payload is None or room_code is None or deadline_at is None:
        return

    # Snapshot current question for reconnects (Redis), then broadcast
    redis = await _redis(runtime)
    try:
        await redis.set(
            match_current_question(match_id),
            json.dumps(question_payload, separators=(",", ":")),
        )
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass

    await _broadcast(
        runtime,
        room_code,
        {
            "type": "question.started",
            "message_id": await _next_message_id(),
            "payload": question_payload,
        },
    )

    # Schedule the close task at the deadline.
    delay = max(0.0, (deadline_at - _utcnow()).total_seconds())
    task = asyncio.create_task(
        _close_question_after(runtime, match_id, position, delay),
        name=f"match-close-{match_id}-{position}",
    )
    sched = _scheduler_singleton()
    await sched.set_active(match_id, task)


async def _close_question_after(
    runtime: MatchRuntime, match_id: int, position: int, delay: float
) -> None:
    """Sleep until the deadline, then run :func:`close_question`.

    Wrapped so the cancellation contract stays simple: cancelling the
    task during sleep is the supported pause path.
    """
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    await close_question(runtime, match_id=match_id, position=position)


# ---------------------------------------------------------------------------
# close_question
# ---------------------------------------------------------------------------


async def close_question(
    runtime: MatchRuntime, *, match_id: int, position: int
) -> None:
    """Stamp ``closed_at``, broadcast ``question.closed``, schedule next or finish."""
    runtime_state_for(match_id, runtime)
    sm = runtime.sessionmaker

    async with sm() as session:
        mq_stmt = (
            select(MatchQuestion)
            .where(
                MatchQuestion.match_id == match_id,
                MatchQuestion.position == position,
            )
            .with_for_update()
        )
        try:
            async with session.begin():
                mq = (await session.execute(mq_stmt)).scalar_one_or_none()
                if mq is None or mq.closed_at is not None:
                    log.info(
                        "close_question: skip match=%s pos=%s already=%s",
                        match_id, position, "closed" if mq and mq.closed_at else "missing",
                    )
                    return
                match = await session.get(Match, match_id)
                if match is None:
                    return
                if match.status != RoomStatus.running:
                    # Pause/end raced past the timer — leave the question
                    # un-closed so resume() (or end_match) can pick up
                    # ownership cleanly.
                    log.info(
                        "close_question: match=%s not running (status=%s) — skip",
                        match_id, match.status.value,
                    )
                    return
                room = await session.get(Room, match.room_id)
                if room is None:
                    return
                opts_stmt = (
                    select(AnswerOption)
                    .where(AnswerOption.question_id == mq.question_id)
                    .order_by(AnswerOption.position.asc())
                )
                options = list((await session.execute(opts_stmt)).scalars().all())
                question = await session.get(Question, mq.question_id)

                closed_at = _utcnow()
                mq.closed_at = closed_at

                # Total questions to know whether to advance
                total_stmt = select(MatchQuestion).where(
                    MatchQuestion.match_id == match_id
                )
                total_questions = len(
                    list((await session.execute(total_stmt)).scalars().all())
                )

                # Outbox QuestionClosed
                correct_ids = [str(o.id) for o in options if o.is_correct]
                payload = {
                    "match_id": str(match_id),
                    "match_question_id": str(mq.id),
                    "question_id": str(mq.question_id),
                    "position": position,
                    "closed_at": _iso(closed_at),
                    "correct_option_ids": correct_ids,
                }
                await register_event(
                    session,
                    event_type=EVT_QUESTION_CLOSED,
                    aggregate_type=AGG_MATCH,
                    aggregate_id=match_id,
                    payload=payload,
                    occurred_at=closed_at,
                )
        except Exception:
            log.exception("close_question commit failed match=%s pos=%s", match_id, position)
            return

        room_code = room.code
        explanation = question.explanation if question is not None else None
        last_question = position >= total_questions

    # Compute accuracy from Redis answered set / submissions count.
    redis = await _redis(runtime)
    try:
        answered_n = await lb_cache.answered_count(redis, match_id, mq.question_id)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass

    accuracy_percent: float | None = None
    if answered_n > 0:
        # Count correct submissions for this question
        async with sm() as session:
            cstmt = select(AnswerSubmission).where(
                AnswerSubmission.match_question_id == mq.id,
                AnswerSubmission.is_correct.is_(True),
            )
            correct_n = len(list((await session.execute(cstmt)).scalars().all()))
        accuracy_percent = round(100.0 * correct_n / max(1, answered_n), 1)

    await _broadcast(
        runtime,
        room_code,
        {
            "type": "question.closed",
            "message_id": await _next_message_id(),
            "payload": {
                "match_question_id": str(mq.id),
                "correct_option_ids": correct_ids,
                "explanation": explanation,
                "accuracy_percent": accuracy_percent,
            },
        },
    )

    if last_question:
        await end_match(runtime, match_id=match_id)
        return

    # Schedule the next question after a small inter-question gap.
    next_position = position + 1
    sleep_s = max(0, runtime.inter_question_seconds)

    async def _gap_then_arm() -> None:
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            return
        await arm_question(runtime, match_id=match_id, position=next_position)

    task = asyncio.create_task(_gap_then_arm(), name=f"match-gap-{match_id}-{next_position}")
    sched = _scheduler_singleton()
    await sched.set_active(match_id, task)


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------


_PAUSE_KEY = "match:{}:pause"


async def pause_match(
    session: AsyncSession,
    runtime: MatchRuntime,
    *,
    host_id: int,
    room_code: str,
) -> Match:
    stmt = select(Room).where(Room.code == room_code).with_for_update()
    room = (await session.execute(stmt)).scalar_one_or_none()
    if room is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="room code not found")
    if room.host_id != host_id:
        raise AuthError("FORBIDDEN", 403, message="not the room host")
    match = await MatchRepo(session).get_by_room_id(room.id)
    if match is None or match.status != RoomStatus.running:
        raise AuthError("ROOM_NOT_JOINABLE", 409, message="no running match")

    # Find the currently-active match question (started, not closed)
    mq_stmt = (
        select(MatchQuestion)
        .where(
            MatchQuestion.match_id == match.id,
            MatchQuestion.started_at.is_not(None),
            MatchQuestion.closed_at.is_(None),
        )
        .order_by(MatchQuestion.position.desc())
        .limit(1)
    )
    mq = (await session.execute(mq_stmt)).scalar_one_or_none()
    remaining_ms = 0
    if mq is not None and mq.deadline_at is not None:
        remaining_ms = max(0, int((mq.deadline_at - _utcnow()).total_seconds() * 1000))

    match.status = RoomStatus.paused
    room.status = RoomStatus.paused
    await session.commit()

    # Cancel the active timer and stash remaining_ms in Redis
    sched = _scheduler_singleton()
    await sched.cancel(match.id)

    redis = await _redis(runtime)
    try:
        await redis.set(
            _PAUSE_KEY.format(match.id),
            json.dumps(
                {
                    "position": mq.position if mq else None,
                    "remaining_ms": remaining_ms,
                },
                separators=(",", ":"),
            ),
            ex=24 * 3600,
        )
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass

    return match


async def resume_match(
    session: AsyncSession,
    runtime: MatchRuntime,
    *,
    host_id: int,
    room_code: str,
) -> Match:
    stmt = select(Room).where(Room.code == room_code).with_for_update()
    room = (await session.execute(stmt)).scalar_one_or_none()
    if room is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="room code not found")
    if room.host_id != host_id:
        raise AuthError("FORBIDDEN", 403, message="not the room host")
    match = await MatchRepo(session).get_by_room_id(room.id)
    if match is None or match.status != RoomStatus.paused:
        raise AuthError("ROOM_NOT_JOINABLE", 409, message="match is not paused")

    redis = await _redis(runtime)
    try:
        raw = await redis.get(_PAUSE_KEY.format(match.id))
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass
    pause_state = json.loads(raw) if raw else {"position": None, "remaining_ms": 0}

    position = pause_state.get("position")
    remaining_ms = int(pause_state.get("remaining_ms") or 0)

    if position is not None:
        mq_stmt = (
            select(MatchQuestion)
            .where(
                MatchQuestion.match_id == match.id,
                MatchQuestion.position == int(position),
            )
            .with_for_update()
        )
        mq = (await session.execute(mq_stmt)).scalar_one_or_none()
        if mq is not None and mq.closed_at is None:
            new_deadline = _utcnow() + timedelta(milliseconds=max(0, remaining_ms))
            mq.deadline_at = new_deadline

    match.status = RoomStatus.running
    room.status = RoomStatus.running
    await session.commit()

    # Re-arm: either continue the same question's timer, or arm next.
    sched = _scheduler_singleton()
    if position is not None and remaining_ms > 0:
        delay = remaining_ms / 1000.0
        task = asyncio.create_task(
            _close_question_after(runtime, match.id, int(position), delay),
            name=f"match-resume-{match.id}-{position}",
        )
        await sched.set_active(match.id, task)
    else:
        # No active question — find the next un-started one
        async with runtime.sessionmaker() as s:
            nstmt = (
                select(MatchQuestion)
                .where(
                    MatchQuestion.match_id == match.id,
                    MatchQuestion.started_at.is_(None),
                )
                .order_by(MatchQuestion.position.asc())
                .limit(1)
            )
            nxt = (await s.execute(nstmt)).scalar_one_or_none()
        if nxt is not None:
            asyncio.create_task(
                arm_question(runtime, match_id=match.id, position=nxt.position),
                name=f"match-arm-{match.id}-{nxt.position}",
            )

    return match


# ---------------------------------------------------------------------------
# end_match
# ---------------------------------------------------------------------------


async def end_match(
    runtime: MatchRuntime, *, match_id: int, host_id: int | None = None
) -> Match:
    """Finalise the match: aggregate final_scores and broadcast finish."""
    sched = _scheduler_singleton()
    await sched.cancel(match_id)

    sm = runtime.sessionmaker
    room_code: str | None = None
    already_completed = False
    completed_match: Match | None = None
    async with sm() as session:
        try:
            async with session.begin():
                match = await session.get(Match, match_id, with_for_update=True)
                if match is None:
                    raise AuthError("ROOM_NOT_FOUND", 404, message="match not found")
                room_stmt = select(Room).where(Room.id == match.room_id).with_for_update()
                room = (await session.execute(room_stmt)).scalar_one_or_none()
                if room is None:
                    raise AuthError("ROOM_NOT_FOUND", 404, message="room not found")
                if host_id is not None and room.host_id != host_id:
                    raise AuthError("FORBIDDEN", 403, message="not the room host")
                if match.status == RoomStatus.completed:
                    already_completed = True
                    completed_match = match
                    room_code = room.code
                else:
                    # Aggregate per-participant from answer_submissions
                    subs_stmt = select(AnswerSubmission).where(
                        AnswerSubmission.match_id == match_id
                    )
                    subs = list((await session.execute(subs_stmt)).scalars().all())

                    per_participant: dict[int, dict[str, Any]] = {}
                    for s in subs:
                        rec = per_participant.setdefault(
                            s.participant_id,
                            {"total": 0, "correct": 0, "rt_sum": 0, "rt_count": 0},
                        )
                        rec["total"] += int(s.score_awarded)
                        rec["correct"] += 1 if s.is_correct else 0
                        rec["rt_sum"] += int(s.response_time_ms)
                        rec["rt_count"] += 1

                    # Include all active room participants so non-answerers still get a row
                    part_stmt = select(RoomParticipant).where(
                        RoomParticipant.room_id == room.id,
                        RoomParticipant.is_kicked.is_(False),
                    )
                    participants = list((await session.execute(part_stmt)).scalars().all())
                    for p in participants:
                        per_participant.setdefault(
                            p.id, {"total": 0, "correct": 0, "rt_sum": 0, "rt_count": 0}
                        )

                    rows: list[tuple[int, int, int, int | None]] = []
                    for pid, agg in per_participant.items():
                        avg_ms = (
                            int(agg["rt_sum"] / agg["rt_count"]) if agg["rt_count"] > 0 else None
                        )
                        rows.append((pid, agg["total"], agg["correct"], avg_ms))

                    # Rank: total DESC, ties by avg_response_ms ASC (None last)
                    def _sort_key(r: tuple[int, int, int, int | None]) -> tuple[int, int]:
                        pid, total, correct, avg_ms = r
                        return (-total, avg_ms if avg_ms is not None else 10**9)

                    rows.sort(key=_sort_key)

                    ended_at = _utcnow()
                    match.status = RoomStatus.completed
                    match.ended_at = ended_at
                    room.status = RoomStatus.completed
                    room.ended_at = ended_at

                    final_payload: list[dict[str, Any]] = []
                    for rank, (pid, total, correct, avg_ms) in enumerate(rows, start=1):
                        fs = FinalScore(
                            match_id=match_id,
                            participant_id=pid,
                            total_score=int(total),
                            correct_count=int(correct),
                            average_response_ms=avg_ms,
                            rank=rank,
                        )
                        session.add(fs)
                        final_payload.append(
                            {
                                "participant_id": str(pid),
                                "total_score": int(total),
                                "correct_count": int(correct),
                                "average_response_ms": avg_ms,
                                "rank": rank,
                            }
                        )

                    await register_event(
                        session,
                        event_type=EVT_MATCH_FINISHED,
                        aggregate_type=AGG_MATCH,
                        aggregate_id=match_id,
                        payload={
                            "match_id": str(match_id),
                            "room_id": str(room.id),
                            "ended_at": _iso(ended_at),
                            "final_scores": final_payload,
                        },
                        occurred_at=ended_at,
                    )
                    room_code = room.code
                    completed_match = match
        except AuthError:
            raise
        except Exception:
            log.exception("end_match failed match=%s", match_id)
            raise

    if already_completed:
        return completed_match  # type: ignore[return-value]

    if room_code is None or completed_match is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="match end produced no state")

    # Post-commit broadcasts + Redis cleanup
    await _broadcast(
        runtime,
        room_code,
        {
            "type": "match.finished",
            "message_id": await _next_message_id(),
            "payload": {
                "match_id": str(match_id),
                "final_leaderboard_url": f"/api/v1/matches/{match_id}/leaderboard",
                "analytics_url": f"/api/v1/matches/{match_id}/analytics",
            },
        },
    )

    redis = await _redis(runtime)
    try:
        writer = RoomSnapshotWriter(
            redis,
            admit_sha=runtime.capacity_admit_sha,
            release_sha=runtime.capacity_release_sha,
        )
        cached = await writer.read(room_code)
        if cached is not None:
            cached.setdefault("room", {})["status"] = RoomStatus.completed.value
            await writer.write(room_code, cached, status=RoomStatus.completed)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass

    return completed_match


# ---------------------------------------------------------------------------
# submit_answer
# ---------------------------------------------------------------------------


async def submit_answer(
    session: AsyncSession,
    runtime: MatchRuntime,
    *,
    match_id: int,
    participant_id: int,
    payload: AnswerSubmitRequest,
    request_id: str,
) -> dict[str, Any]:
    """Canonical answer submission tx (per docs/05).

    Returns the JSON-serialisable response dict the REST endpoint will
    surface and the WS push will mirror as ``answer.accepted``.
    """
    if not request_id:
        raise AuthError("VALIDATION_ERROR", 422, message="X-Request-ID is required")

    redis = Redis(connection_pool=runtime.redis_pool)
    try:
        # 1. Idempotency cache hit
        cached = await idem_cache.get(redis, request_id)
        if cached is not None:
            return cached

        match_question_id = int(payload.match_question_id)

        # Returned-from-tx fields used by the post-commit hooks below.
        room_code: str | None = None
        participant_nick: str = ""
        score_awarded: int = 0
        response_time_ms: int = 0
        is_correct: bool = False
        submission_id: int | None = None
        question_id: int | None = None
        # Sentinel: set when the inner savepoint hit a unique-constraint
        # collision, in which case the response was already populated
        # from the existing row and the outer tx should commit with no
        # new submission/outbox row.
        idem_response: dict[str, Any] | None = None

        async with session.begin():
            # 2. Lock match_question
            mq_stmt = (
                select(MatchQuestion)
                .where(MatchQuestion.id == match_question_id)
                .with_for_update()
            )
            mq = (await session.execute(mq_stmt)).scalar_one_or_none()
            if mq is None or mq.match_id != match_id:
                raise AuthError(
                    "VALIDATION_ERROR", 422, message="match_question not found"
                )

            match = await session.get(Match, match_id)
            if match is None:
                raise AuthError("ROOM_NOT_FOUND", 404, message="match not found")

            # 3. Deadline + status check (200 ms grace)
            now = _utcnow()
            if match.status != RoomStatus.running:
                raise AuthError(
                    "QUESTION_CLOSED", 409, message="match not running"
                )
            if mq.closed_at is not None:
                raise AuthError("QUESTION_CLOSED", 409, message="question closed")
            if mq.deadline_at is None or mq.started_at is None:
                raise AuthError("QUESTION_CLOSED", 409, message="question not armed")
            effective_deadline = mq.deadline_at + timedelta(
                milliseconds=DEADLINE_GRACE_MS
            )
            if now > effective_deadline:
                raise AuthError("QUESTION_CLOSED", 409, message="deadline passed")

            # 4. Participant must belong to this match's room and not be kicked
            pstmt = select(RoomParticipant).where(
                RoomParticipant.id == participant_id,
                RoomParticipant.room_id == match.room_id,
            )
            participant = (await session.execute(pstmt)).scalar_one_or_none()
            if participant is None or participant.is_kicked:
                raise AuthError(
                    "FORBIDDEN",
                    403,
                    message="participant not in this match's room or is kicked",
                )

            # 5. Compute is_correct
            opts_stmt = select(AnswerOption).where(
                AnswerOption.question_id == mq.question_id
            )
            options = list((await session.execute(opts_stmt)).scalars().all())
            correct_set = {o.id for o in options if o.is_correct}
            selected_ids = {int(x) for x in payload.selected_option_ids}
            valid_ids = {o.id for o in options}
            if not selected_ids.issubset(valid_ids):
                raise AuthError(
                    "VALIDATION_ERROR",
                    422,
                    message="selected_option_ids must belong to this question",
                )
            is_correct = selected_ids == correct_set and len(correct_set) > 0

            # 6. Score
            response_time_ms = int(
                max(0.0, (now - mq.started_at).total_seconds() * 1000)
            )
            deadline_ms = int(
                (mq.deadline_at - mq.started_at).total_seconds() * 1000
            )
            question = await session.get(Question, mq.question_id)
            points = int(question.points) if question is not None else 0
            room = await session.get(Room, match.room_id)
            mode = "speed_bonus"
            if room and isinstance(room.settings, dict):
                mode = str(room.settings.get("scoring_mode") or "speed_bonus")
            score_awarded = scoring_service.score(
                points,
                response_time_ms,
                deadline_ms,
                mode=mode,
                is_correct=is_correct,
            )

            room_code = room.code if room else None
            participant_nick = participant.nickname
            question_id = mq.question_id

            # 7. Insert submission inside a SAVEPOINT so a unique-constraint
            #    collision rolls back only this insert; the outer tx stays
            #    usable for fetching the existing row.
            gen = get_id_generator()
            submission = AnswerSubmission(
                id=gen.next_id(),
                match_id=match_id,
                match_question_id=mq.id,
                participant_id=participant_id,
                selected_option_ids=sorted(selected_ids),
                is_correct=is_correct,
                score_awarded=int(score_awarded),
                response_time_ms=response_time_ms,
                request_id=request_id,
            )
            inserted = True
            try:
                async with session.begin_nested():
                    session.add(submission)
                    await session.flush()
            except IntegrityError:
                inserted = False

            if not inserted:
                # ux_submission_request OR ux_submission_once collided;
                # both paths resolve to the canonical existing response.
                rstmt = select(AnswerSubmission).where(
                    AnswerSubmission.request_id == request_id
                )
                existing = (await session.execute(rstmt)).scalar_one_or_none()
                if existing is None:
                    estmt = select(AnswerSubmission).where(
                        AnswerSubmission.match_question_id == mq.id,
                        AnswerSubmission.participant_id == participant_id,
                    )
                    existing = (await session.execute(estmt)).scalar_one_or_none()
                if existing is None:
                    raise AuthError(
                        "ANSWER_ALREADY_SUBMITTED",
                        409,
                        message="duplicate but original not found",
                    )
                idem_response = {
                    "submission_id": existing.id,
                    "accepted": True,
                    "is_correct": existing.is_correct,
                    "score_awarded": int(existing.score_awarded),
                    "response_time_ms": int(existing.response_time_ms),
                    "leaderboard_rank": None,
                }
            else:
                submission_id = submission.id
                # 8. Outbox AnswerSubmitted (only on the genuine-insert path)
                await register_event(
                    session,
                    event_type=EVT_ANSWER_SUBMITTED,
                    aggregate_type=AGG_ANSWER,
                    aggregate_id=submission.id,
                    payload={
                        "submission_id": str(submission.id),
                        "match_id": str(match_id),
                        "room_id": str(match.room_id),
                        "match_question_id": str(mq.id),
                        "question_id": str(mq.question_id),
                        "participant_id": str(participant_id),
                        "is_correct": is_correct,
                        "score_awarded": int(score_awarded),
                        "response_time_ms": response_time_ms,
                        "submitted_at": _iso(now),
                    },
                    occurred_at=now,
                )

        # 9. If the unique-violation path resolved, write the idempotency
        #    cache and return without touching the live leaderboard
        #    (the original request's hook already updated it).
        if idem_response is not None:
            cached_form = {
                **idem_response,
                "submission_id": str(idem_response["submission_id"]),
            }
            await idem_cache.set(redis, request_id, cached_form)
            return idem_response

        # 9. Post-commit hooks (best-effort). Wrapped in a single
        #    ``leaderboard.update`` span so the ZADD + read + broadcast show
        #    up as one subtree under the HTTP request span (the child Redis
        #    command spans nest underneath it).
        rank: int | None = None
        with otel_span("leaderboard.update", **{"match.id": str(match_id)}):
            await lb_cache.zadd_total(
                redis,
                match_id,
                participant_id,
                int(score_awarded),
                sha=runtime.leaderboard_sha,
            )
            if question_id is not None:
                await lb_cache.mark_answered(
                    redis, match_id, question_id, participant_id
                )
            await lb_cache.set_nicknames(
                redis, match_id, [(participant_id, participant_nick)]
            )

            # Compute leaderboard rank for this participant
            top10 = await lb_cache.top(redis, match_id, n=10)
            for entry in top10:
                if str(entry["participant_id"]) == str(participant_id):
                    rank = int(entry["rank"])
                    break

            version = int(await redis.incr(f"match:{match_id}:lb_version") or 0)
            if room_code is not None:
                await _broadcast(
                    runtime,
                    room_code,
                    {
                        "type": "leaderboard.updated",
                        "message_id": await _next_message_id(),
                        "payload": {
                            "version": version,
                            "top": top10,
                        },
                    },
                )

        app_metrics.record_answer_submission(
            is_correct=is_correct, response_time_ms=response_time_ms
        )

        response = {
            "submission_id": submission_id,
            "accepted": True,
            "is_correct": is_correct,
            "score_awarded": int(score_awarded),
            "response_time_ms": response_time_ms,
            "leaderboard_rank": rank,
        }
        cached_form = {**response, "submission_id": str(submission_id)}
        await idem_cache.set(redis, request_id, cached_form)
        return response
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Read leaderboard (live or final)
# ---------------------------------------------------------------------------


async def read_leaderboard(
    session: AsyncSession,
    runtime: MatchRuntime,
    *,
    match_id: int,
    limit: int = 10,
) -> dict[str, Any]:
    match = await session.get(Match, match_id)
    if match is None:
        raise AuthError("ROOM_NOT_FOUND", 404, message="match not found")

    if match.status == RoomStatus.completed:
        # Final leaderboard from Postgres
        from app.repositories.leaderboard_snapshot_repo import LeaderboardSnapshotRepo

        rows = await LeaderboardSnapshotRepo(session).list_by_match_ordered_by_rank(match_id)
        # Build participant nickname map
        if rows:
            pids = [r.participant_id for r in rows]
            pstmt = select(RoomParticipant).where(RoomParticipant.id.in_(pids))
            parts = list((await session.execute(pstmt)).scalars().all())
            nick_by_id = {p.id: p.nickname for p in parts}
        else:
            nick_by_id = {}
        entries = [
            {
                "rank": r.rank,
                "participant_id": str(r.participant_id),
                "nickname": nick_by_id.get(r.participant_id, ""),
                "score": int(r.total_score),
            }
            for r in rows[:limit]
        ]
        return {"match_id": match_id, "is_final": True, "entries": entries}

    if get_settings().leaderboard_backend == "pg":
        score_expr = func.coalesce(
            func.sum(AnswerSubmission.score_awarded), 0
        ).label("score")
        avg_rt_expr = func.coalesce(
            func.avg(AnswerSubmission.response_time_ms), 0
        ).label("avg_rt")
        pg_rows = list(
            (
                await session.execute(
                    select(
                        AnswerSubmission.participant_id,
                        score_expr,
                        avg_rt_expr,
                    )
                    .where(AnswerSubmission.match_id == match_id)
                    .group_by(AnswerSubmission.participant_id)
                    .order_by(desc(score_expr), avg_rt_expr.asc())
                    .limit(limit)
                )
            ).all()
        )
        pg_nick_by_id: dict[int, str] = {}
        if pg_rows:
            pids = [int(row.participant_id) for row in pg_rows]
            parts = list(
                (
                    await session.execute(
                        select(RoomParticipant).where(RoomParticipant.id.in_(pids))
                    )
                )
                .scalars()
                .all()
            )
            pg_nick_by_id = {p.id: p.nickname for p in parts}
        entries = [
            {
                "rank": idx,
                "participant_id": str(row.participant_id),
                "nickname": pg_nick_by_id.get(int(row.participant_id), ""),
                "score": int(row.score),
            }
            for idx, row in enumerate(pg_rows, start=1)
        ]
        return {"match_id": match_id, "is_final": False, "entries": entries}

    redis = await _redis(runtime)
    try:
        entries = await lb_cache.top(redis, match_id, n=limit)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass
    return {"match_id": match_id, "is_final": False, "entries": entries}


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


async def recover_running_matches(runtime: MatchRuntime) -> int:
    """Scan ``matches WHERE status='running'`` and re-arm timers.

    Called from the FastAPI lifespan on startup. For each running match
    we look at the last ``started_at`` match_question that hasn't been
    closed: if its deadline has already passed, fire ``close_question``
    immediately; otherwise schedule it for the remaining duration.
    Matches with no started question yet get their first question armed.
    Returns the number of matches recovered for logging.
    """
    sm = runtime.sessionmaker
    recovered = 0
    async with sm() as session:
        stmt = select(Match).where(Match.status == RoomStatus.running)
        matches = list((await session.execute(stmt)).scalars().all())

    for m in matches:
        runtime_state_for(m.id, runtime)
        async with sm() as session:
            mq_stmt = (
                select(MatchQuestion)
                .where(
                    MatchQuestion.match_id == m.id,
                    MatchQuestion.started_at.is_not(None),
                    MatchQuestion.closed_at.is_(None),
                )
                .order_by(MatchQuestion.position.desc())
                .limit(1)
            )
            mq = (await session.execute(mq_stmt)).scalar_one_or_none()
            if mq is None:
                # No active question — arm next un-started one (if any)
                nstmt = (
                    select(MatchQuestion)
                    .where(
                        MatchQuestion.match_id == m.id,
                        MatchQuestion.started_at.is_(None),
                    )
                    .order_by(MatchQuestion.position.asc())
                    .limit(1)
                )
                nxt = (await session.execute(nstmt)).scalar_one_or_none()
                if nxt is not None:
                    asyncio.create_task(
                        arm_question(runtime, match_id=m.id, position=nxt.position),
                        name=f"recover-arm-{m.id}-{nxt.position}",
                    )
                    recovered += 1
                continue

        if mq.deadline_at is None:
            continue
        delay = max(0.0, (mq.deadline_at - _utcnow()).total_seconds())
        if delay <= 0:
            asyncio.create_task(
                close_question(runtime, match_id=m.id, position=mq.position),
                name=f"recover-close-{m.id}-{mq.position}",
            )
        else:
            task = asyncio.create_task(
                _close_question_after(runtime, m.id, mq.position, delay),
                name=f"recover-close-{m.id}-{mq.position}",
            )
            sched = _scheduler_singleton()
            await sched.set_active(m.id, task)
        recovered += 1
    return recovered


# ---------------------------------------------------------------------------
# Module-level scheduler singleton
# ---------------------------------------------------------------------------


_scheduler: MatchScheduler | None = None


def _scheduler_singleton() -> MatchScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MatchScheduler()
    return _scheduler


def reset_scheduler_for_tests() -> None:
    """Test helper: drop the singleton and pending runtime registry."""
    global _scheduler
    _scheduler = None
    _runtime_by_match.clear()
