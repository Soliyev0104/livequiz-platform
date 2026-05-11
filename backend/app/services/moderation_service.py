"""Moderation service (P09).

Rule-based content scanning + report creation/decision flow. The
banned-words policy lives at ``ops/moderation/banned_words.json`` so the
list can be edited without a code change; the file is loaded once at
import time and cached.

Transactional model:

- ``auto_flag_on_publish`` / ``auto_flag_on_join`` are inline helpers
  called from inside other service transactions (quiz publish, room
  join). They only ``flush`` — the outer caller owns the commit so a
  publish-validation failure rolls the flag rows back too.
- ``create_report`` and ``decide`` are public entry points called from
  the API router. Each one owns its DB transaction (``session.commit()``
  at the end) and emits one or more outbox events in the same txn.

The mute decision additionally publishes a synthetic
``participant.kicked`` envelope to ``ws:room:{code}``. The WS connection
manager translates that into a close 4002 for the matching participant.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.keys import ws_room
from app.core.ids import get_id_generator
from app.core.security import AuthError
from app.db.models.audit_log import AuditLog
from app.db.models.enums import (
    ModerationStatus,
    QuizVisibility,
    UserRole,
)
from app.db.models.moderation_report import ModerationReport
from app.db.models.quiz_set import QuizSet
from app.db.models.room import Room
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User
from app.events.types import (
    AGG_MODERATION,
    EVT_CONTENT_FLAGGED,
    EVT_CONTENT_REPORTED,
    EVT_MODERATION_DECISION,
)
from app.repositories.audit_repo import AuditRepo
from app.repositories.moderation_repo import ModerationRepo
from app.repositories.outbox_repo import OutboxRepo
from app.repositories.quiz_repo import QuizRepo
from app.repositories.room_repo import RoomRepo
from app.repositories.user_repo import UserRepo
from app.services.outbox_service import register_event

log = logging.getLogger("app.services.moderation")


# ---------------------------------------------------------------------------
# Banned-words policy loader
# ---------------------------------------------------------------------------


def _candidate_policy_paths() -> list[Path]:
    """Possible locations of ``banned_words.json`` across runtimes.

    The same source tree is invoked from three different file layouts:
      * Local dev: ``<repo>/backend/app/services/moderation_service.py``
        → ``<repo>/ops/moderation/banned_words.json``.
      * Docker (``COPY ./backend /app``): ``/app/app/services/...``
        → ``/app/ops/moderation/...`` (mounted via compose).
      * Tests run from the source tree share the local-dev layout.

    An explicit ``BANNED_WORDS_PATH`` env var wins so operators can
    point at a curated policy without changing code.
    """
    import os

    paths: list[Path] = []
    override = os.environ.get("BANNED_WORDS_PATH")
    if override:
        paths.append(Path(override))
    here = Path(__file__).resolve()
    # Walk a few parents looking for an ``ops/moderation/banned_words.json``.
    for p in (here.parents[3], here.parents[2], here.parents[1]):
        paths.append(p / "ops" / "moderation" / "banned_words.json")
    # Docker COPY puts the project root at /app.
    paths.append(Path("/app/ops/moderation/banned_words.json"))
    return paths


@dataclass(frozen=True)
class _Policy:
    words: tuple[str, ...] = ()
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = ()


def _resolve_policy_path() -> Path | None:
    for p in _candidate_policy_paths():
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def _load_policy() -> _Policy:
    path = _resolve_policy_path()
    if path is None:
        log.warning(
            "banned_words.json not found in any candidate path — moderation rules disabled"
        )
        return _Policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("failed to parse %s: %s", path, exc)
        return _Policy()

    words_raw = data.get("words") or []
    patterns_raw = data.get("patterns") or []
    words: list[str] = []
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for w in words_raw:
        if isinstance(w, str) and w.strip():
            words.append(w.strip().lower())
    for p in patterns_raw:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "pattern")
        regex_src = p.get("regex")
        if not isinstance(regex_src, str):
            continue
        try:
            compiled = re.compile(regex_src, re.IGNORECASE)
        except re.error as exc:
            log.warning("skipping invalid moderation regex %r: %s", name, exc)
            continue
        patterns.append((name, compiled))
    return _Policy(words=tuple(words), patterns=tuple(patterns))


_policy: _Policy = _load_policy()


def reload_policy() -> None:
    """Force a re-read of the policy file (used by tests)."""
    global _policy
    _policy = _load_policy()


# ---------------------------------------------------------------------------
# scan_text
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Flag:
    reason: str
    context: str
    matched: str
    details: dict[str, Any] = field(default_factory=dict)


def scan_text(text: str | None, context: str) -> list[Flag]:
    """Case-insensitive substring + regex scan against banned-words list.

    ``context`` is an opaque label (e.g. ``"nickname"``, ``"quiz.title"``)
    carried into each :class:`Flag` so downstream consumers can render
    the offending field. An empty / falsy ``text`` returns ``[]``.
    """
    if not text:
        return []
    lowered = text.lower()
    flags: list[Flag] = []
    for word in _policy.words:
        if word and word in lowered:
            flags.append(
                Flag(
                    reason="banned_word",
                    context=context,
                    matched=word,
                    details={"strategy": "substring"},
                )
            )
    for name, pattern in _policy.patterns:
        match = pattern.search(text)
        if match is not None:
            flags.append(
                Flag(
                    reason="banned_pattern",
                    context=context,
                    matched=match.group(0),
                    details={"pattern": name, "strategy": "regex"},
                )
            )
    return flags


# ---------------------------------------------------------------------------
# Auto-flag helpers (called inside other service transactions — no commit)
# ---------------------------------------------------------------------------


async def auto_flag_on_publish(
    session: AsyncSession, *, quiz_set: QuizSet
) -> list[ModerationReport]:
    """Scan the quiz title/description/questions/options on publish.

    Creates one ``moderation_reports`` row per distinct flag, status
    ``pending``. Insertion does not block the publish — the caller still
    commits the transaction and returns success. Emits one
    ``ContentFlagged`` outbox event per flag in the same transaction.

    Quiz-question and option iteration tolerates lazy collections that
    might not be loaded; we skip non-iterable ``questions`` attributes
    so callers can pass a partially-hydrated row without crashing.
    """
    fields_to_scan: list[tuple[str, str | None]] = [
        ("quiz.title", quiz_set.title),
        ("quiz.description", quiz_set.description),
    ]
    questions = getattr(quiz_set, "questions", None) or []
    try:
        iter(questions)
    except TypeError:
        questions = []
    for q in questions:
        fields_to_scan.append((f"question.{q.position}.body", getattr(q, "body", None)))
        for o in getattr(q, "options", None) or []:
            fields_to_scan.append(
                (f"question.{q.position}.option.{o.position}.body", getattr(o, "body", None))
            )

    flat_flags: list[tuple[str, Flag]] = []
    for ctx, text in fields_to_scan:
        for f in scan_text(text, ctx):
            flat_flags.append((ctx, f))
    if not flat_flags:
        return []

    return await _persist_flags(
        session,
        flags=flat_flags,
        reporter_user_id=None,
        room_id=None,
        target_user_id=None,
        target_quiz_set_id=quiz_set.id,
        source="quiz.publish",
    )


async def auto_flag_on_join(
    session: AsyncSession,
    *,
    room: Room,
    nickname: str,
    user_id: int | None,
) -> list[ModerationReport]:
    """Scan a player nickname at room-join time.

    Returns the inserted report rows. The join itself proceeds even when
    flags are raised — moderation is informational, not gating. Emits one
    ``ContentFlagged`` outbox event per flag.
    """
    flags = scan_text(nickname, "nickname")
    if not flags:
        return []
    return await _persist_flags(
        session,
        flags=[("nickname", f) for f in flags],
        reporter_user_id=None,
        room_id=room.id,
        target_user_id=user_id,
        target_quiz_set_id=None,
        source="room.join",
    )


async def _persist_flags(
    session: AsyncSession,
    *,
    flags: list[tuple[str, Flag]],
    reporter_user_id: int | None,
    room_id: int | None,
    target_user_id: int | None,
    target_quiz_set_id: int | None,
    source: str,
) -> list[ModerationReport]:
    gen = get_id_generator()
    repo = ModerationRepo(session)
    rows: list[ModerationReport] = []
    for ctx, flag in flags:
        report = ModerationReport(
            id=gen.next_id(),
            reporter_user_id=reporter_user_id,
            room_id=room_id,
            target_user_id=target_user_id,
            target_quiz_set_id=target_quiz_set_id,
            reason=flag.reason[:120],
            details=json.dumps(
                {
                    "context": ctx,
                    "matched": flag.matched,
                    "source": source,
                    **flag.details,
                },
                separators=(",", ":"),
            ),
            status=ModerationStatus.pending,
        )
        await repo.add(report)
        await register_event(
            session,
            event_type=EVT_CONTENT_FLAGGED,
            aggregate_type=AGG_MODERATION,
            aggregate_id=report.id,
            payload={
                "report_id": str(report.id),
                "reason": flag.reason,
                "context": ctx,
                "matched": flag.matched,
                "source": source,
                "target_user_id": str(target_user_id) if target_user_id else None,
                "target_quiz_set_id": str(target_quiz_set_id) if target_quiz_set_id else None,
                "room_id": str(room_id) if room_id else None,
            },
        )
        rows.append(report)
    return rows


# ---------------------------------------------------------------------------
# create_report (public — owns its transaction)
# ---------------------------------------------------------------------------


async def create_report(
    session: AsyncSession,
    *,
    reporter_user_id: int | None,
    room_id: int | None,
    target_user_id: int | None,
    target_quiz_set_id: int | None,
    reason: str,
    details: str | None,
) -> ModerationReport:
    """Insert a moderation report from a player/host action.

    Exactly one of ``room_id`` / ``target_user_id`` / ``target_quiz_set_id``
    is expected — the API schema enforces XOR, but we also defend against
    direct service callers by raising ``VALIDATION_ERROR``.
    Emits a ``ContentReported`` outbox event in the same transaction.
    """
    set_count = sum(
        1 for t in (room_id, target_user_id, target_quiz_set_id) if t is not None
    )
    if set_count != 1:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="exactly one target field is required",
            details={"got": set_count},
        )

    gen = get_id_generator()
    repo = ModerationRepo(session)
    report = ModerationReport(
        id=gen.next_id(),
        reporter_user_id=reporter_user_id,
        room_id=room_id,
        target_user_id=target_user_id,
        target_quiz_set_id=target_quiz_set_id,
        reason=reason[:120],
        details=details,
        status=ModerationStatus.pending,
    )
    await repo.add(report)

    await register_event(
        session,
        event_type=EVT_CONTENT_REPORTED,
        aggregate_type=AGG_MODERATION,
        aggregate_id=report.id,
        payload={
            "report_id": str(report.id),
            "reporter_user_id": str(reporter_user_id) if reporter_user_id else None,
            "room_id": str(room_id) if room_id else None,
            "target_user_id": str(target_user_id) if target_user_id else None,
            "target_quiz_set_id": str(target_quiz_set_id) if target_quiz_set_id else None,
            "reason": reason,
        },
    )
    await session.commit()
    return report


# ---------------------------------------------------------------------------
# decide (public — owns its transaction)
# ---------------------------------------------------------------------------


_DECISIONS = ("dismiss", "hide", "mute", "ban")


async def decide(
    session: AsyncSession,
    redis: Redis,
    *,
    moderator: User,
    report_id: int,
    decision: str,
    reason: str | None = None,
) -> ModerationReport:
    """Apply a moderator's decision to a pending report.

    Branching:
      - ``dismiss`` → status=dismissed, audit log only.
      - ``hide`` → target quiz set: visibility=private, is_published=false,
        version+1.
      - ``mute`` → mark every active room participant matching the
        target as ``is_kicked=True``; broadcast ``participant.kicked`` on
        ``ws:room:{code}`` so the WS layer closes their sockets.
      - ``ban`` → target user.is_active=false.

    All branches write an ``audit_logs`` row and emit a
    ``ModerationDecisionMade`` outbox event in the same transaction.
    """
    if decision not in _DECISIONS:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message=f"unknown decision {decision!r}",
            details={"allowed": list(_DECISIONS)},
        )

    repo = ModerationRepo(session)
    report = await repo.get_by_id(report_id)
    if report is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="report not found",
            details={"report_id": str(report_id)},
        )
    if report.status != ModerationStatus.pending:
        raise AuthError(
            "VALIDATION_ERROR",
            409,
            message="report already decided",
            details={"status": report.status.value},
        )

    # Apply the action. Each branch records what was affected so the
    # audit row + outbox event carry concrete entity ids.
    affected: dict[str, Any] = {"decision": decision, "reason": reason}
    mute_targets: list[tuple[str, int]] = []  # (room_code, participant_id)

    if decision == "dismiss":
        new_status = ModerationStatus.dismissed
    else:
        new_status = ModerationStatus.action_taken

    if decision == "hide":
        await _apply_hide(session, report, affected)
    elif decision == "mute":
        mute_targets = await _apply_mute(session, report, affected)
    elif decision == "ban":
        await _apply_ban(session, report, affected)

    now = datetime.now(timezone.utc)
    await repo.update_status(
        report,
        status=new_status,
        reviewer_id=moderator.id,
        reviewed_at=now,
    )

    # Audit log
    gen = get_id_generator()
    audit = AuditLog(
        id=gen.next_id(),
        actor_user_id=moderator.id,
        action=f"moderation.decide.{decision}",
        entity_type="moderation_report",
        entity_id=report.id,
        audit_metadata=_jsonable(affected),
    )
    await AuditRepo(session).add(audit)

    # Outbox event
    await register_event(
        session,
        event_type=EVT_MODERATION_DECISION,
        aggregate_type=AGG_MODERATION,
        aggregate_id=report.id,
        payload={
            "report_id": str(report.id),
            "decision": decision,
            "reason": reason,
            "moderator_user_id": str(moderator.id),
            "status": new_status.value,
            "affected": _jsonable(affected),
        },
    )

    await session.commit()

    # Best-effort WS close fan-out for mute decisions. The Redis publish
    # is outside the DB transaction because the participant.is_kicked
    # flag has already been committed — even if the publish drops, the
    # next WS handshake will see the row and refuse to admit.
    for room_code, participant_id in mute_targets:
        envelope = {
            "type": "participant.kicked",
            "message_id": str(gen.next_id()),
            "payload": {
                "participant_id": str(participant_id),
                "reason": "muted",
                "report_id": str(report.id),
            },
        }
        try:
            await redis.publish(ws_room(room_code), json.dumps(envelope, separators=(",", ":")))
        except Exception as exc:  # noqa: BLE001 — broadcast best-effort
            log.warning("failed to publish participant.kicked room=%s: %s", room_code, exc)

    return report


# ---------------------------------------------------------------------------
# Decision implementations
# ---------------------------------------------------------------------------


async def _apply_hide(
    session: AsyncSession,
    report: ModerationReport,
    affected: dict[str, Any],
) -> None:
    if report.target_quiz_set_id is None:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="hide requires a target_quiz_set_id",
            details={"report_id": str(report.id)},
        )
    quiz = await QuizRepo(session).get_by_id(report.target_quiz_set_id)
    if quiz is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="target quiz set not found",
            details={"target_quiz_set_id": str(report.target_quiz_set_id)},
        )
    quiz.visibility = QuizVisibility.private
    quiz.is_published = False
    quiz.version = (quiz.version or 1) + 1
    await session.flush()
    affected.update(
        {
            "quiz_set_id": str(quiz.id),
            "visibility": quiz.visibility.value,
            "is_published": quiz.is_published,
            "version": quiz.version,
        }
    )


async def _apply_mute(
    session: AsyncSession,
    report: ModerationReport,
    affected: dict[str, Any],
) -> list[tuple[str, int]]:
    """Mark the matching active room participant(s) as kicked.

    A mute may be scoped to a single room (when ``report.room_id`` is
    set) or to every active room a target user is currently in (when
    only ``target_user_id`` is set). We return ``(room_code, participant_id)``
    tuples so the caller can publish ``participant.kicked`` once per
    affected participant.
    """
    from sqlalchemy import select

    stmt = select(RoomParticipant, Room).join(Room, Room.id == RoomParticipant.room_id).where(
        RoomParticipant.left_at.is_(None),
        RoomParticipant.is_kicked.is_(False),
    )
    if report.room_id is not None:
        stmt = stmt.where(RoomParticipant.room_id == report.room_id)
    if report.target_user_id is not None:
        stmt = stmt.where(RoomParticipant.user_id == report.target_user_id)
    if report.room_id is None and report.target_user_id is None:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="mute requires room_id and/or target_user_id",
            details={"report_id": str(report.id)},
        )

    rows = (await session.execute(stmt)).all()
    targets: list[tuple[str, int]] = []
    for participant, room in rows:
        participant.is_kicked = True
        targets.append((room.code, participant.id))
    await session.flush()
    affected["muted_participants"] = [
        {"room_code": code, "participant_id": str(pid)} for code, pid in targets
    ]
    return targets


async def _apply_ban(
    session: AsyncSession,
    report: ModerationReport,
    affected: dict[str, Any],
) -> None:
    if report.target_user_id is None:
        raise AuthError(
            "VALIDATION_ERROR",
            422,
            message="ban requires a target_user_id",
            details={"report_id": str(report.id)},
        )
    user = await UserRepo(session).get_by_id(report.target_user_id)
    if user is None:
        raise AuthError(
            "VALIDATION_ERROR",
            404,
            message="target user not found",
            details={"target_user_id": str(report.target_user_id)},
        )
    user.is_active = False
    await session.flush()
    affected.update({"user_id": str(user.id), "is_active": False})


# ---------------------------------------------------------------------------
# Target preview helper for the queue endpoint
# ---------------------------------------------------------------------------


async def build_target_preview(
    session: AsyncSession, report: ModerationReport
) -> dict[str, str | None] | None:
    """Render a tiny preview block per report.

    Looks up the human-readable label (quiz title, user display name,
    room code) without hitting any related table the route hasn't
    already paid for. Returns ``None`` when the report has no target
    (legacy rows or freshly created ones that wired only a reporter).
    """
    if report.target_quiz_set_id is not None:
        quiz = await QuizRepo(session).get_by_id(report.target_quiz_set_id)
        return {
            "kind": "quiz_set",
            "id": str(report.target_quiz_set_id),
            "label": quiz.title if quiz else None,
        }
    if report.target_user_id is not None:
        user = await UserRepo(session).get_by_id(report.target_user_id)
        return {
            "kind": "user",
            "id": str(report.target_user_id),
            "label": user.display_name if user else None,
        }
    if report.room_id is not None:
        room = await RoomRepo(session).get_by_id(report.room_id)
        return {
            "kind": "room",
            "id": str(report.room_id),
            "label": room.code if room else None,
        }
    return None


# ---------------------------------------------------------------------------
# Compatibility shim used by P04 publish-flow (no-op now superseded by
# auto_flag_on_publish, but kept so the existing call site stays stable).
# ---------------------------------------------------------------------------


async def scan_quiz(quiz_set: QuizSet) -> None:
    """Pre-publish hook — legacy no-op signature.

    Returning ``None`` keeps the contract from P04 intact (cleanly =
    "no fatal moderation issue raised"). Side-effecting auto-flagging is
    done by ``auto_flag_on_publish`` from inside the publish flow.
    """
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Coerce values that JSON cannot natively serialise."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (ModerationStatus, QuizVisibility, UserRole)):
        return value.value
    return value


__all__: Iterable[str] = (
    "Flag",
    "auto_flag_on_join",
    "auto_flag_on_publish",
    "build_target_preview",
    "create_report",
    "decide",
    "reload_policy",
    "scan_quiz",
    "scan_text",
)
