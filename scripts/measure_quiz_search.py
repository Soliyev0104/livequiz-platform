"""Measurement B — quiz search before/after the trigram GIN index.

Drops ``ix_quiz_sets_title_trgm``, runs ``EXPLAIN ANALYZE`` 10×, recreates
the index, runs the same EXPLAIN 10×, and writes a markdown report at
``scripts/measurements/B_quiz_search.md``. Idempotent on re-run.

Run from inside the api-a container, or with ``DATABASE_URL`` pointing
at the docker-compose Postgres:

    docker compose exec api-a python scripts/measure_quiz_search.py
"""

from __future__ import annotations

import asyncio
import os
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


_QUERY = (
    "EXPLAIN (ANALYZE, BUFFERS) "
    "SELECT * FROM quiz_sets WHERE title ILIKE '%network%' LIMIT 20"
)
_DROP_INDEX = "DROP INDEX IF EXISTS ix_quiz_sets_title_trgm"
_CREATE_INDEX = (
    "CREATE INDEX ix_quiz_sets_title_trgm ON quiz_sets "
    "USING gin (title gin_trgm_ops)"
)

_DATASET_SIZE = 20_000
_RUNS = 10


_THEMED_WORDS = [
    "Networks",
    "Networking",
    "Network",
    "Database",
    "Databases",
    "Algorithm",
    "Algorithms",
    "Operating Systems",
    "Compilers",
    "Distributed Systems",
    "Security",
    "Cryptography",
    "Machine Learning",
    "Statistics",
    "Calculus",
    "Topology",
    "Graph Theory",
    "Discrete Math",
    "Linear Algebra",
    "Geometry",
]
_SUFFIXES = [
    "Basics",
    "Drills",
    "Exam Prep",
    "Practice Set",
    "Quick Quiz",
    "Advanced",
    "Quiz",
    "101",
    "Crash Course",
    "Survey",
]


@dataclass
class PhaseResult:
    name: str
    timings_ms: list[float]
    sample_plan: str

    @property
    def stats(self) -> dict[str, float]:
        if not self.timings_ms:
            return {"min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        sorted_ms = sorted(self.timings_ms)
        n = len(sorted_ms)
        p50 = statistics.median(sorted_ms)
        # Closest-rank p95 — fine for n=10.
        p95 = sorted_ms[max(0, int(0.95 * (n - 1)))]
        return {
            "min": sorted_ms[0],
            "p50": p50,
            "p95": p95,
            "max": sorted_ms[-1],
        }


def _scan_type(plan_text: str) -> str:
    if "Bitmap Index Scan on ix_quiz_sets_title_trgm" in plan_text:
        return "Bitmap Index Scan (GIN trigram)"
    if "Index Scan" in plan_text:
        return "Index Scan"
    if "Bitmap Heap Scan" in plan_text:
        return "Bitmap Heap Scan"
    return "Seq Scan"


def _extract_execution_time_ms(plan_text: str) -> float:
    # Postgres prints e.g. "Execution Time: 12.345 ms" on the last line.
    for line in plan_text.splitlines():
        line = line.strip()
        if line.startswith("Execution Time:"):
            try:
                return float(line.split(":", 1)[1].strip().split(" ", 1)[0])
            except (IndexError, ValueError):
                return 0.0
    return 0.0


def _explain_text(rows: list) -> str:
    return "\n".join(row[0] for row in rows)


async def _seed(session) -> None:
    await session.execute(
        text(
            "TRUNCATE quiz_sets, quiz_set_tags, quiz_tags, "
            "questions, answer_options RESTART IDENTITY CASCADE"
        )
    )

    # Snowflake worker_id may not be configured for ad-hoc runs; mint plain
    # bigserial-style IDs by hand. Worker_id 9 is the test-mode default and
    # is safe inside the api-a container.
    from app.core.ids import get_id_generator

    gen = get_id_generator()
    owner_id = gen.next_id()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role, "
            "is_active) VALUES (:id, :email, 'x', 'Bench', 'host', TRUE)"
        ),
        {"id": owner_id, "email": f"bench-{owner_id}@livequiz.local"},
    )

    rng = random.Random(42)
    rows: list[dict[str, object]] = []
    for _ in range(_DATASET_SIZE):
        title = (
            f"{rng.choice(_THEMED_WORDS)} {rng.choice(_SUFFIXES)} "
            f"#{rng.randint(1, 9999)}"
        )
        rows.append({"id": gen.next_id(), "owner_id": owner_id, "title": title})

    # Bulk insert in chunks.
    chunk = 500
    for i in range(0, len(rows), chunk):
        await session.execute(
            text(
                "INSERT INTO quiz_sets (id, owner_id, title, visibility, "
                "is_published, version) "
                "VALUES (:id, :owner_id, :title, 'public', TRUE, 1)"
            ),
            rows[i : i + chunk],
        )
    await session.execute(text("ANALYZE quiz_sets"))
    await session.commit()


async def _run_phase(
    sm,
    *,
    name: str,
    before_setup: str | None,
    force_index: bool = False,
) -> PhaseResult:
    """Execute the EXPLAIN ANALYZE query ``_RUNS`` times.

    ``force_index=True`` runs each query inside its own transaction with
    ``SET LOCAL enable_seqscan = off`` so the planner has to use the
    trigram index. Without this nudge, the planner often prefers a
    sequential scan even on tens of thousands of rows because the LIMIT
    20 makes a partial seq scan competitive.
    """
    timings: list[float] = []
    sample_plan = ""
    if before_setup is not None:
        async with sm() as s:
            await s.execute(text(before_setup))
            await s.commit()

    for i in range(_RUNS):
        async with sm() as s:
            if force_index:
                await s.execute(text("SET LOCAL enable_seqscan = off"))
            rows = (await s.execute(text(_QUERY))).all()
            plan_text = _explain_text(rows)
            timings.append(_extract_execution_time_ms(plan_text))
            if i == 0:
                sample_plan = plan_text
            if force_index:
                await s.rollback()
    return PhaseResult(name=name, timings_ms=timings, sample_plan=sample_plan)


def _format_report(before: PhaseResult, after: PhaseResult) -> str:
    bs = before.stats
    as_ = after.stats
    lines: list[str] = []
    lines.append("# Measurement B — Quiz search\n")
    lines.append(
        f"Dataset: **{_DATASET_SIZE}** quiz_sets rows. "
        f"Each phase ran the same query **{_RUNS}** times.\n"
    )
    lines.append(f"Query:\n\n```sql\n{_QUERY}\n```\n")
    lines.append("## Timings\n")
    lines.append(
        "| Phase | min ms | p50 ms | p95 ms | max ms | scan type |\n"
        "|---|---:|---:|---:|---:|---|"
    )
    lines.append(
        f"| {before.name} | {bs['min']:.3f} | {bs['p50']:.3f} | "
        f"{bs['p95']:.3f} | {bs['max']:.3f} | "
        f"{_scan_type(before.sample_plan)} |"
    )
    lines.append(
        f"| {after.name} | {as_['min']:.3f} | {as_['p50']:.3f} | "
        f"{as_['p95']:.3f} | {as_['max']:.3f} | "
        f"{_scan_type(after.sample_plan)} |"
    )
    lines.append("\n## Plan — before (no trigram index)\n")
    lines.append(f"```\n{before.sample_plan}\n```")
    lines.append("\n## Plan — after (`ix_quiz_sets_title_trgm` present)\n")
    lines.append(f"```\n{after.sample_plan}\n```\n")
    return "\n".join(lines)


async def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print(
            "DATABASE_URL is not set; run inside the api-a container.",
            file=sys.stderr,
        )
        return 2

    engine = create_async_engine(db_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as s:
            await _seed(s)

        before = await _run_phase(
            sm, name="before", before_setup=_DROP_INDEX, force_index=False
        )
        after = await _run_phase(
            sm, name="after", before_setup=_CREATE_INDEX, force_index=True
        )

        report = _format_report(before, after)
        out_path = (
            Path(__file__).resolve().parent / "measurements" / "B_quiz_search.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
