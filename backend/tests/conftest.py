"""Shared pytest fixtures.

Integration tests run against a real PostGIS instance (started once per session
via testcontainers) so that geometry columns and spatial queries behave exactly
as they do in production — something SQLite cannot emulate.

Isolation strategy: the schema is created once; every test runs against it and
all tables are truncated afterwards. The app's `get_db` dependency is overridden
to use a session bound to the test engine.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

import app.models  # noqa: F401  — registers every model on Base.metadata
from app.api.deps import get_db, get_pricing_service, get_redis
from app.core.redis import RedisCache
from app.db.base import Base
from app.main import app
from app.services.pricing_service import PricingService


class _NoSurgePricing(PricingService):
    """Pricing service that never touches the network: surge is always 1.0.
    Keeps the real compute_fare formula. Default for tests; surge-specific tests
    override get_pricing_service themselves."""

    async def get_surge_multiplier(self, geohash_zone: str) -> float:
        return 1.0


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped loop so session-scoped async fixtures share one loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_url() -> AsyncGenerator[str, None]:
    """Boot a PostGIS container for the whole test session; yield an asyncpg URL.

    testcontainers' readiness probe uses the sync psycopg2 driver, so we let it
    build that URL and then swap the driver for asyncpg for the app/test engine.
    """
    with PostgresContainer("postgis/postgis:15-3.3") as postgres:
        sync_url = postgres.get_connection_url()  # postgresql+psycopg2://...
        yield sync_url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest_asyncio.fixture(scope="session")
async def engine(postgres_url):
    # NullPool: never reuse a connection across asyncio loops. pytest-asyncio's
    # per-test loops otherwise inherit a pooled asyncpg connection bound to a
    # different loop ("attached to a different loop").
    eng = create_async_engine(postgres_url, future=True, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def redis_url() -> AsyncGenerator[str, None]:
    """Boot a Redis container for the test session."""
    with RedisContainer("redis:7-alpine") as redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def cache(redis_url) -> AsyncGenerator[RedisCache, None]:
    """Function-scoped Redis connection (fresh per test to avoid cross-loop
    affinity), flushed clean on setup. The container itself is session-scoped."""
    rc = RedisCache()
    await rc.start(redis_url)
    await rc._redis.flushdb()
    yield rc
    await rc.stop()


@pytest_asyncio.fixture(autouse=True)
async def _truncate(engine) -> AsyncGenerator[None, None]:
    """Wipe Postgres tables after each test for isolation (FK-safe via CASCADE)."""
    yield
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    if tables:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")
            )


@pytest_asyncio.fixture
async def db(engine, _truncate) -> AsyncGenerator[AsyncSession, None]:
    """A session for tests to read/write directly (assertions, fixtures)."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine, cache) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired to the app with get_db/get_redis pointing at the test
    Postgres and Redis containers."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = lambda: cache
    # Default: a pricing service with no HTTP client, so it never hits the
    # network (surge API unreachable -> multiplier 1.0). Tests that exercise
    # surge behaviour override this themselves.
    app.dependency_overrides[get_pricing_service] = lambda: _NoSurgePricing(cache)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --- Convenience fixtures/helpers --------------------------------------------
@pytest_asyncio.fixture
async def registered_user(client) -> dict:
    """Register a default rider and return the request payload + response body."""
    payload = {
        "email": "rider@example.com",
        "password": "supersecret123",
        "full_name": "Test Rider",
        "phone": "+15550001111",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return {"payload": payload, "user": resp.json()}


@pytest_asyncio.fixture
async def auth_tokens(client, registered_user) -> dict:
    """Log the default user in and return the token pair."""
    payload = registered_user["payload"]
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def auth_headers(auth_tokens) -> dict:
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}


@pytest_asyncio.fixture
async def driver_headers(client) -> dict:
    """Register + log in a driver-role user; return its auth header."""
    payload = {
        "email": "driver@example.com",
        "password": "supersecret123",
        "full_name": "Test Driver",
        "role": "driver",
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture
async def driver_profile(client, driver_headers) -> dict:
    """A driver-role user with a created driver profile. Returns {headers, driver}."""
    resp = await client.post(
        "/api/v1/drivers",
        headers=driver_headers,
        json={
            "vehicle_make": "Toyota",
            "vehicle_model": "Prius",
            "vehicle_plate": "ABC123",
            "vehicle_color": "Silver",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"headers": driver_headers, "driver": resp.json()}
