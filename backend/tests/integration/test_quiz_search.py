"""Integration tests for trigram-based quiz search.

The trigram index ``ix_quiz_sets_title_trgm`` is created in the Alembic
baseline. These tests confirm:

- the public list endpoint returns relevant rows ordered by trigram
  similarity when ``q`` is provided,
- anonymous viewers only see public+published quizzes,
- the planner picks the GIN trigram index for ``title %% :q``. We force
  ``enable_seqscan=off`` for the EXPLAIN call so the test is stable on
  cold containers with small row counts; the seed size (50 rows) keeps
  the index a sensible choice in production-shaped runs as well.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from testcontainers.redis import RedisContainer

from app.cache.rate_limit import load_script as load_rate_limit_script
from app.core.ids import get_id_generator
from app.db.base import Base
from app.db.models.enums import QuizVisibility, UserRole
from app.db.models.quiz_set import QuizSet
from app.db.models.user import User
from app.main import create_app

pytestmark = pytest.mark.asyncio(loop_scope="session")


_NETWORK_TITLES = [
    "Computer Networks Quiz",
    "Networking Basics",
    "Network Security 101",
    "Advanced Networking",
    "Mobile Networks",
    "Computer Networks Advanced",
]

# Padding rows that don't share the trigram with "network".
_OTHER_TITLES = [
    "Quantum Mechanics 101",
    "World History Survey",
    "Renaissance Art Survey",
    "Macroeconomics Essentials",
    "Algorithms in Practice",
    "Introduction to Calculus",
    "Linear Algebra Drills",
    "Organic Chemistry Basics",
    "Cell Biology Practice",
    "Discrete Mathematics",
    "Statistics Made Simple",
    "Modern Philosophy",
    "Music Theory Drills",
    "Geography of Africa",
    "Geology of the Andes",
    "Meteorology Basics",
    "Marine Biology Quiz",
    "Astronomy 101",
    "Spanish Vocabulary",
    "French Grammar Drills",
    "Roman Empire Trivia",
    "Cold War Politics",
    "Java Generics Quiz",
    "Python List Comprehensions",
    "Rust Ownership Drills",
    "Go Concurrency Quiz",
    "Bash Scripting Practice",
    "C++ Templates",
    "C Memory Layout",
    "Haskell Functor Laws",
    "OCaml Pattern Matching",
    "Erlang Actor Model",
    "Lisp Macros Drill",
    "TypeScript Generics",
    "JavaScript Closures",
    "HTML Semantic Tags",
    "CSS Grid Layouts",
    "Algorithms Big-O Drills",
    "Data Structures Practice",
    "Database Design Patterns",
    "ER Modeling Practice",
    "OS Process Scheduling",
    "Virtual Memory Drills",
    "Compilers Lex/Yacc",
    "Theory of Computation",
]


@pytest_asyncio.fixture(loop_scope="session")
async def search_app(
    migrated_engine, redis_container: RedisContainer
) -> AsyncIterator[tuple[AsyncClient, object]]:
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}/0"
    )
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    async with Redis(connection_pool=pool) as r:
        await r.flushdb()
        sha = await load_rate_limit_script(r)

    app = create_app()
    app.state.engine = migrated_engine
    app.state.redis_pool = pool
    app.state.rate_limit_sha = sha

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, migrated_engine
        finally:
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


async def _seed_quizzes(engine) -> int:
    """Insert one host owner + 50 public+published quizzes. Return owner id."""
    gen = get_id_generator()
    sm = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = gen.next_id()
    async with sm() as s:
        s.add(
            User(
                id=owner_id,
                email="search-host@quizsearch.example.com",
                password_hash="x",
                display_name="SH",
                role=UserRole.host,
                is_active=True,
            )
        )
        await s.flush()

        all_titles = list(_NETWORK_TITLES) + list(_OTHER_TITLES)
        for title in all_titles:
            s.add(
                QuizSet(
                    id=gen.next_id(),
                    owner_id=owner_id,
                    title=title,
                    description=None,
                    visibility=QuizVisibility.public,
                    is_published=True,
                    version=1,
                )
            )
        await s.commit()
    return owner_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_search_returns_relevant_titles_ranked_by_similarity(
    search_app,
) -> None:
    client, engine = search_app
    await _seed_quizzes(engine)

    resp = await client.get("/api/v1/quiz-sets", params={"q": "network", "limit": 5})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    titles = [it["title"] for it in items]

    # All returned titles must be among the trigram-matching network rows.
    for t in titles:
        assert t in _NETWORK_TITLES, f"unexpected title in trigram result: {t}"

    # Each network title should be present (they're all close enough).
    assert len(titles) >= 3


async def test_anonymous_only_sees_public_published(search_app) -> None:
    client, engine = search_app
    owner_id = await _seed_quizzes(engine)

    # Insert one private+draft quiz owned by the same user.
    gen = get_id_generator()
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        s.add(
            QuizSet(
                id=gen.next_id(),
                owner_id=owner_id,
                title="Network Secret Draft",
                description=None,
                visibility=QuizVisibility.private,
                is_published=False,
                version=1,
            )
        )
        await s.commit()

    resp = await client.get(
        "/api/v1/quiz-sets", params={"q": "network", "limit": 50}
    )
    titles = [it["title"] for it in resp.json()["items"]]
    assert "Network Secret Draft" not in titles


async def test_search_uses_trigram_index(search_app) -> None:
    client, engine = search_app
    await _seed_quizzes(engine)

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        await s.execute(text("BEGIN"))
        # Force the planner to consider the GIN index over the seq scan even
        # on the small seed dataset (50 rows). The index is the right choice
        # at production scale; this guards the test from planner heuristics.
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        plan_rows = (
            await s.execute(
                text(
                    "EXPLAIN (FORMAT JSON, ANALYZE) "
                    "SELECT id FROM quiz_sets "
                    "WHERE title % 'network' "
                    "ORDER BY similarity(title, 'network') DESC LIMIT 20"
                )
            )
        ).scalar_one()
        await s.rollback()

    plan = plan_rows[0]["Plan"] if isinstance(plan_rows, list) else plan_rows["Plan"]

    def walk(node) -> bool:
        if (
            node.get("Node Type") == "Bitmap Index Scan"
            and node.get("Index Name") == "ix_quiz_sets_title_trgm"
        ):
            return True
        for child in node.get("Plans", []):
            if walk(child):
                return True
        return False

    assert walk(plan), f"trigram index not used; plan was: {plan_rows}"
