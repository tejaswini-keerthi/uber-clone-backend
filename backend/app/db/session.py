"""Async SQLAlchemy engine and session factory.

A single engine (connection pool) is created at import time and reused for the
process lifetime; `app.main`'s lifespan disposes it on shutdown. Routes never
touch the engine directly — they receive an `AsyncSession` via the `get_db`
dependency in `app.api.deps`, which wraps each request in a transaction.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# echo follows debug so SQL is visible in dev logs but quiet in production.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,  # transparently recycle stale connections
    future=True,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # objects remain usable after commit (response serialization)
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session bound to a transaction, committing on success and rolling
    back on error. This is the low-level generator; FastAPI wires it through
    `app.api.deps.get_db`."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
