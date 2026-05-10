"""Async DB session helpers.

- Module-level lazy `AsyncEngine` (pool_size=10, max_overflow=20, pool_pre_ping=True).
- `async_sessionmaker(expire_on_commit=False)` so post-commit code can read attrs.
- `get_session()` FastAPI dependency: one session per request, rolls back on
  exception, never auto-commits.
- `_post_commit_hooks` ContextVar + `register_post_commit` / `run_post_commit_hooks`
  used by P07 to fire Redis/WS effects after `session.commit()` returns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from inspect import isawaitable
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

PostCommitHook = Callable[[], Awaitable[None] | None]

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_post_commit_hooks: ContextVar[list[PostCommitHook]] = ContextVar(
    "_post_commit_hooks", default=[]
)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield one AsyncSession per request.

    Rolls back on exception. Never auto-commits — services own their txns.
    The post-commit-hooks ContextVar is reset for every request so hooks
    registered in one request never leak into another.
    """
    token = _post_commit_hooks.set([])
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
        _post_commit_hooks.reset(token)


def register_post_commit(hook: PostCommitHook) -> None:
    """Queue a callable (sync or async) to fire after the request commits.

    Drained by `run_post_commit_hooks()`. Hooks run in registration order;
    a hook raising propagates and skips the rest.
    """
    _post_commit_hooks.get().append(hook)


async def run_post_commit_hooks() -> None:
    """Drain and execute hooks queued with `register_post_commit`.

    Always clears the queue, even if a hook raises, so a partially-failed
    drain never re-fires the survivors on the next call.
    """
    hooks = _post_commit_hooks.get()
    if not hooks:
        return
    try:
        for hook in hooks:
            result = hook()
            if isawaitable(result):
                await result
    finally:
        hooks.clear()


async def dispose_engine() -> None:
    """Test/lifespan helper — disposes the lazy engine if it was built."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
