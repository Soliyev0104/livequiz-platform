"""FastAPI application factory.

Phase 00 surface area:
  GET /api/v1/health   liveness, returns {"status": "ok"}
  GET /api/v1/ready    readiness, pings Postgres + Redis

ClickHouse is not pinged in P00; it is a soft dependency until P08.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings, get_settings

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine: AsyncEngine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )
    redis_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    app.state.settings = settings
    app.state.engine = engine
    app.state.redis_pool = redis_pool
    log.info("startup: service=%s worker_id=%s", settings.service_name, settings.snowflake_worker_id)
    try:
        yield
    finally:
        await engine.dispose()
        await redis_pool.disconnect()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LiveQuiz API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, str]:
        result: dict[str, str] = {}
        # Postgres
        try:
            async with app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["db"] = "ok"
        except Exception as exc:  # noqa: BLE001 - readiness must always answer
            log.warning("readiness: db check failed: %s", exc)
            result["db"] = "fail"
        # Redis
        try:
            async with Redis(connection_pool=app.state.redis_pool) as r:
                pong = await r.ping()
            result["redis"] = "ok" if pong else "fail"
        except Exception as exc:  # noqa: BLE001
            log.warning("readiness: redis check failed: %s", exc)
            result["redis"] = "fail"
        # ClickHouse — wired in P08
        result["clickhouse"] = "skipped"
        return result

    # P03+ routers will mount here. Empty for now.
    # from app.api.v1 import auth, users, quiz_sets, rooms, matches, analytics, moderation
    return app


app = create_app()
