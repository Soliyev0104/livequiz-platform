"""Common FastAPI dependencies.

Stubs in P00; concrete sessions are wired in P02 (DB) and P05 (Redis).
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    engine = request.app.state.engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def get_redis(request: Request) -> AsyncIterator[Redis]:
    pool = request.app.state.redis_pool
    async with Redis(connection_pool=pool) as client:
        yield client
