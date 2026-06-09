"""FastAPI application entrypoint.

Wires up the lifespan (startup/shutdown of external resources), CORS, and the
v1 API routers. Business logic lives in the service layer — this module only
assembles the app. Routers and the Kafka/Redis/DB resources are attached to
their respective subsystems in later build steps; the lifespan here is the
single place those connections are opened and closed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import AppError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open external connections on startup, close them on shutdown.

    Subsequent build steps register their resources here:
      - Step 2: database engine disposal
      - Step 8: Kafka producer start/stop
      - Step 6/9: Redis connection pool
    Keeping it centralized means a single, predictable shutdown path.
    """
    logger.info("Starting %s (env=%s)", settings.app_name, settings.environment)

    # Redis cache (best-effort: the app runs without it, just without caching).
    try:
        from app.core.redis import redis_cache

        await redis_cache.start()
    except Exception as exc:  # pragma: no cover - optional in tests
        logger.warning("Redis not connected: %s", exc)

    # Kafka producer (started here once the producer module exists in step 8).
    try:
        from app.core.kafka import kafka_producer

        await kafka_producer.start()
    except Exception as exc:  # pragma: no cover - optional in early steps/tests
        logger.warning("Kafka producer not started: %s", exc)

    yield

    try:
        from app.core.redis import redis_cache

        await redis_cache.stop()
    except Exception:  # pragma: no cover
        pass

    try:
        from app.core.kafka import kafka_producer

        await kafka_producer.stop()
    except Exception:  # pragma: no cover
        pass

    # Dispose the DB engine so connections are released cleanly.
    try:
        from app.db.session import engine

        await engine.dispose()
    except Exception:  # pragma: no cover
        pass

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten per-environment in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        """Single translation point: domain errors -> HTTP responses. Lets the
        service/repository layers stay framework-agnostic."""
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=headers
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    # v1 routers are included as each lands. Included independently so a module
    # that doesn't exist yet (later build steps) doesn't suppress the others.
    _register_routers(app)
    return app


def _register_routers(app: FastAPI) -> None:
    prefix = settings.api_v1_prefix
    specs = [
        ("auth", prefix),
        ("users", prefix),
        ("drivers", prefix),
        ("rides", prefix),
        ("websocket", None),  # ws routes are not API-prefixed
    ]
    import importlib

    for name, router_prefix in specs:
        try:
            module = importlib.import_module(f"app.api.v1.routes.{name}")
        except ImportError as exc:
            logger.info("Router '%s' not yet available: %s", name, exc)
            continue
        if router_prefix:
            app.include_router(module.router, prefix=router_prefix)
        else:
            app.include_router(module.router)


app = create_app()
