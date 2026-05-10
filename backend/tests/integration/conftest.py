"""Integration test fixtures using testcontainers.

Postgres is session-scoped and started up-front because every integration
test (including migration tests) needs it. Redis / Kafka / ClickHouse are
defined but only spun up when a test asks for them — keeps phase-02 tests
(which only need Postgres) cheap.

`db_session` is function-scoped: it opens an `AsyncSession`, yields, then
on teardown runs `TRUNCATE … RESTART IDENTITY CASCADE` against every table
in `Base.metadata.sorted_tables`. Cheaper than re-running migrations.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.clickhouse import ClickHouseContainer
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# Set test-mode env BEFORE any app module imports so config picks them up.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SNOWFLAKE_WORKER_ID", "9")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://livequiz:livequiz@localhost:5432/livequiz"
)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """Postgres container shared across the test session.

    Image pinned to `postgres:16-alpine` to match docker-compose.yml so any
    extension/SQL behaviour parity-tests against production-shaped images.
    """
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def postgres_url(postgres_container: PostgresContainer) -> str:
    """asyncpg URL for the running Postgres container."""
    url = postgres_container.get_connection_url()
    # testcontainers may emit psycopg2-flavoured URLs; coerce to asyncpg.
    return url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrated_engine(postgres_url: str):
    """Run alembic upgrade head once per session, yield a connected engine.

    Importing app modules here is safe — env vars are set at module import
    above, before any app config is read.
    """
    os.environ["DATABASE_URL"] = postgres_url
    from app.core.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo_root / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.get_running_loop().run_in_executor(
        None, command.upgrade, cfg, "head"
    )

    engine = create_async_engine(postgres_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(migrated_engine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session; truncates every table on teardown."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.base import Base

    sessionmaker = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()

    table_names = ", ".join(
        f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables)
    )
    async with migrated_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


# --- Lazy infra containers (only spun up when a test requests them) -------


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture(scope="session")
def kafka_container() -> Iterator[KafkaContainer]:
    with KafkaContainer() as k:
        yield k


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator[ClickHouseContainer]:
    with ClickHouseContainer("clickhouse/clickhouse-server:24.8") as ch:
        yield ch
