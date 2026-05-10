"""Seed entrypoint — `python -m app.db.seed` from inside the api container.

Imports `migrations.seeds.*` (mounted at `/app/migrations` by docker-compose)
and runs them in order (users → quizzes → demo room) inside one transaction.
Each underlying seed function is idempotent on natural keys, so re-running
this script is safe and converges to the same end state.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from migrations.seeds import seed_demo_room, seed_quizzes, seed_users

from app.core.ids import get_id_generator
from app.db.session import dispose_engine, get_sessionmaker

log = logging.getLogger("app.db.seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def main() -> int:
    get_id_generator()  # fail-fast on missing SNOWFLAKE_WORKER_ID
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        users = await seed_users.run(session)
        host = users["host@livequiz.local"]
        quizzes = await seed_quizzes.run(session, host)
        await seed_demo_room.run(
            session,
            host=host,
            quiz=quizzes["Computer Networks basics"],
        )
        await session.commit()

    log.info(
        "seed: users=%d quiz_sets=%d demo_room=DEMO01",
        len(users),
        len(quizzes),
    )
    await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
