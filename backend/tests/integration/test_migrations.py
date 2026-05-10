"""Migration up/down/up cycle test.

Spins up its own fresh Postgres testcontainer (function-scoped), runs
`alembic upgrade head`, then `downgrade base`, then `upgrade head` again,
and asserts that all 15 tables and the named functional/partial/GIN
indexes exist after the cycle.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

EXPECTED_TABLES = {
    "users",
    "quiz_sets",
    "quiz_tags",
    "quiz_set_tags",
    "questions",
    "answer_options",
    "rooms",
    "room_participants",
    "matches",
    "match_questions",
    "answer_submissions",
    "final_scores",
    "moderation_reports",
    "audit_logs",
    "outbox_events",
}

# Indexes whose existence proves the hand-written DDL ran. Plain B-tree
# indexes are auto-detected by Alembic, so the smoke test focuses on the
# ones that only exist if 0001_baseline.py emitted raw SQL or named
# constraints correctly.
EXPECTED_INDEXES = {
    "ux_users_email_lower",
    "ix_quiz_sets_public_published",
    "ix_quiz_sets_title_trgm",
    "ux_room_participant_nickname",
    "ix_outbox_unpublished",
    "ux_submission_request",
    "ix_final_scores_rank",
    "ux_questions_quiz_position",
    "ux_answer_options_question_position",
}


def _alembic_config(url: str):
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo_root / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _run_cycle(url: str) -> None:
    """upgrade head → downgrade base → upgrade head (in a worker thread)."""
    from alembic import command

    cfg = _alembic_config(url)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, command.upgrade, cfg, "head")
    await loop.run_in_executor(None, command.downgrade, cfg, "base")
    await loop.run_in_executor(None, command.upgrade, cfg, "head")


@pytest.mark.asyncio
async def test_migration_up_down_up_creates_all_tables_and_indexes() -> None:
    # Use a fresh container so we can downgrade to an empty schema without
    # interfering with the session-scoped postgres_container.
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        )
        os.environ["DATABASE_URL"] = url
        from app.core.config import get_settings

        get_settings.cache_clear()  # type: ignore[attr-defined]

        await _run_cycle(url)

        engine = create_async_engine(url, future=True)
        try:
            async with engine.connect() as conn:
                table_rows = await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                tables = {row[0] for row in table_rows}
                missing_tables = EXPECTED_TABLES - tables
                assert not missing_tables, (
                    f"Missing tables after up/down/up cycle: {missing_tables}"
                )

                index_rows = await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                )
                indexes = {row[0] for row in index_rows}
                missing_indexes = EXPECTED_INDEXES - indexes
                assert not missing_indexes, (
                    f"Missing indexes after up/down/up cycle: {missing_indexes}"
                )
        finally:
            await engine.dispose()
