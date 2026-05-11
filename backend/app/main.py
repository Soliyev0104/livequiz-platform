"""FastAPI application factory.

Surface area:
  GET  /api/v1/health        liveness, returns {"status": "ok"}
  GET  /api/v1/ready         readiness, pings Postgres + Redis
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  POST /api/v1/auth/refresh
  POST /api/v1/auth/logout
  GET  /api/v1/me
  GET  /api/v1/users/{id}    (admin-only)
  GET    /api/v1/quiz-sets                       (P04)
  POST   /api/v1/quiz-sets                       (P04, host-only)
  GET    /api/v1/quiz-sets/{id}                  (P04)
  PATCH  /api/v1/quiz-sets/{id}                  (P04, owner-only)
  POST   /api/v1/quiz-sets/{id}/publish          (P04, owner-only)
  POST   /api/v1/quiz-sets/{id}/questions        (P04, owner-only)
  PATCH  /api/v1/questions/{id}                  (P04, owner-only)
  DELETE /api/v1/questions/{id}                  (P04, owner-only)
  POST   /api/v1/rooms                           (P05, host-only)
  GET    /api/v1/rooms/{code}                    (P05)
  POST   /api/v1/rooms/{code}/join               (P05, optional auth)
  POST   /api/v1/rooms/{code}/start              (P07, host-only)
  POST   /api/v1/rooms/{code}/pause              (P07, host-only)
  POST   /api/v1/rooms/{code}/resume             (P07, host-only)
  POST   /api/v1/rooms/{code}/end                (P07, host-only)
  POST   /api/v1/matches/{id}/answers            (P07, participant token)
  GET    /api/v1/matches/{id}/leaderboard        (P07, participant token)
  WS     /ws/rooms/{code}                        (P06, participant token)

ClickHouse is not pinged in P00; it is a soft dependency until P08.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.api.v1 import analytics as analytics_router
from app.api.v1 import auth as auth_router
from app.api.v1 import matches as matches_router
from app.api.v1 import moderation as moderation_router
from app.api.v1 import questions as questions_router
from app.api.v1 import quiz_sets as quiz_sets_router
from app.api.v1 import rooms as rooms_router
from app.api.v1 import users as users_router
from app.cache import leaderboard as lb_cache
from app.cache.rate_limit import load_script as load_rate_limit_script
from app.cache.redis import load_capacity_scripts
from app.core.config import get_settings
from app.core.ids import get_id_generator
from app.core.middleware import RequestIDMiddleware, register_exception_handlers
from app.services import match_service
from app.ws import router as ws_router
from app.ws.connection_manager import ConnectionManager
from app.ws.redis_pubsub import start_pubsub_task, stop_pubsub_task

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    get_id_generator()  # fail-fast: raises if SNOWFLAKE_WORKER_ID is missing or out of range
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

    # Pre-load the rate-limit Lua so EVALSHA can be used per-request without
    # paying the SCRIPT LOAD round-trip every login. P05 also loads the two
    # capacity-admission scripts (admit + compensating release) used by
    # ``RoomSnapshotWriter``. P07 adds the leaderboard increment script.
    async with Redis(connection_pool=redis_pool) as r:
        app.state.rate_limit_sha = await load_rate_limit_script(r)
        admit_sha, release_sha = await load_capacity_scripts(r)
        app.state.capacity_admit_sha = admit_sha
        app.state.capacity_release_sha = release_sha
        app.state.leaderboard_sha = await lb_cache.load_script(r)

    # P06: per-replica WebSocket plumbing. The ``replica_id`` is the
    # tag used by ``ConnectionManager.broadcast_all`` to suppress its
    # own pub/sub loopback. The pattern listener subscribes once to
    # ``ws:room:*`` so per-room sub/unsub churn is avoided.
    replica_id = uuid.uuid4().hex
    manager = ConnectionManager(replica_id=replica_id)
    pubsub_redis = Redis(connection_pool=redis_pool)
    pubsub_task, _ready = await start_pubsub_task(pubsub_redis, manager)
    app.state.replica_id = replica_id
    app.state.connection_manager = manager
    app.state.pubsub_redis = pubsub_redis
    app.state.pubsub_task = pubsub_task

    # P07: long-lived sessionmaker + match runtime for the scheduler tasks.
    # Scheduler tasks fire after the originating request has returned, so
    # they cannot share its request-scoped session.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    runtime = match_service.MatchRuntime(
        sessionmaker=sessionmaker,
        redis_pool=redis_pool,
        connection_manager=manager,
        capacity_admit_sha=admit_sha,
        capacity_release_sha=release_sha,
        leaderboard_sha=app.state.leaderboard_sha,
    )
    app.state.match_runtime = runtime
    app.state.match_scheduler = match_service._scheduler_singleton()

    # Re-arm timers for any match left running by a previous process crash.
    try:
        recovered = await match_service.recover_running_matches(runtime)
        if recovered:
            log.info("startup: recovered %d running match(es)", recovered)
    except Exception as exc:  # noqa: BLE001 — recovery must not block startup
        log.warning("match recovery failed: %s", exc)

    log.info(
        "startup: service=%s worker_id=%s replica_id=%s",
        settings.service_name,
        settings.snowflake_worker_id,
        replica_id,
    )
    try:
        yield
    finally:
        try:
            await app.state.match_scheduler.cancel_all()
        except Exception:  # noqa: BLE001
            pass
        await stop_pubsub_task(pubsub_task)
        try:
            await pubsub_redis.aclose()
        except Exception:  # noqa: BLE001
            pass
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

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

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
        # ClickHouse (P08). A failure here downgrades analytics to the
        # Postgres fallback path; it must NOT mark the API unready.
        try:
            import asyncio

            from clickhouse_connect import get_client as _ch_client

            def _ping() -> bool:
                client = _ch_client(
                    dsn=settings.clickhouse_url,
                    database=settings.clickhouse_db,
                    connect_timeout=1,
                    send_receive_timeout=2,
                )
                try:
                    rows = client.query("SELECT 1").result_rows
                    return bool(rows and rows[0][0] == 1)
                finally:
                    client.close()

            ch_ok = await asyncio.wait_for(asyncio.to_thread(_ping), timeout=2.5)
            result["clickhouse"] = "ok" if ch_ok else "degraded"
        except Exception as exc:  # noqa: BLE001
            log.info("readiness: clickhouse check degraded: %s", exc)
            result["clickhouse"] = "degraded"
        return result

    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(users_router.router, prefix="/api/v1")
    app.include_router(quiz_sets_router.router, prefix="/api/v1")
    app.include_router(questions_router.router, prefix="/api/v1")
    app.include_router(rooms_router.router, prefix="/api/v1")
    # P07 host-control endpoints sit under /rooms/{code}/{start,pause,resume,end}
    # and the participant-facing answer/leaderboard surface under /matches/...
    app.include_router(matches_router.room_router, prefix="/api/v1")
    app.include_router(matches_router.match_router, prefix="/api/v1")
    # P08: /matches/{id}/analytics — sits under /matches/ alongside the
    # P07 match endpoints. Registered as its own router so the
    # dual-mode (host OR participant) auth dep is local.
    app.include_router(analytics_router.router, prefix="/api/v1")
    # P09 moderation surface: POST /reports + GET/POST /moderation/reports/*
    app.include_router(moderation_router.router, prefix="/api/v1")
    # WebSocket router lives at the top level (no /api/v1 prefix) per
    # docs/07_websocket_protocol.md and the Nginx /ws/* proxy rule.
    app.include_router(ws_router.router)
    return app


app = create_app()
