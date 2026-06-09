"""FastAPI dependency-injection providers.

This module is the seam between the API layer and everything below it. Routes
declare what they need (a DB session, the current user, a service) via
`Depends(...)` and never construct those things themselves.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import InactiveUserError, InvalidTokenError
from app.core.kafka import KafkaPublisher, kafka_producer
from app.core.redis import RedisCache, redis_cache
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import AsyncSessionFactory, get_session
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.driver_service import DriverService
from app.services.pricing_service import PricingService
from app.services.ride_service import RideService
from app.services.user_service import UserService


# --- Database ---
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Per-request async DB session (commit on success, rollback on error)."""
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_session_factory() -> async_sessionmaker:
    """The session factory itself (not a session).

    WebSocket endpoints use this to open a short-lived session for auth and then
    release it — they must not hold a DB connection for the socket's lifetime.
    Overridden in tests to bind to the test engine."""
    return AsyncSessionFactory


SessionFactoryDep = Annotated[async_sessionmaker, Depends(get_session_factory)]


# --- Redis ---
def get_redis() -> RedisCache:
    """The process-wide Redis cache (no-op when not connected). Overridden in
    tests to point at a throwaway Redis container."""
    return redis_cache


RedisDep = Annotated[RedisCache, Depends(get_redis)]


# --- Kafka ---
def get_kafka() -> KafkaPublisher:
    """The process-wide Kafka producer (best-effort; no-op when unavailable).
    Overridden in tests with a recorder."""
    return kafka_producer


KafkaDep = Annotated[KafkaPublisher, Depends(get_kafka)]


# --- Services ---
def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_user_service(db: DbSession) -> UserService:
    return UserService(db)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_driver_service(db: DbSession, redis: RedisDep) -> DriverService:
    return DriverService(db, redis)


DriverServiceDep = Annotated[DriverService, Depends(get_driver_service)]


def get_pricing_service(redis: RedisDep) -> PricingService:
    return PricingService(redis)


PricingServiceDep = Annotated[PricingService, Depends(get_pricing_service)]


def get_ride_service(
    db: DbSession, redis: RedisDep, kafka: KafkaDep, pricing: PricingServiceDep
) -> RideService:
    return RideService(db, redis, kafka, pricing)


RideServiceDep = Annotated[RideService, Depends(get_ride_service)]


# --- Current user ---
# HTTPBearer (rather than OAuth2PasswordBearer) because login takes a JSON body,
# not a form — this gives a clean "Bearer <token>" entry in the OpenAPI docs.
bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """Resolve the access token to a User. Rejects refresh tokens (wrong type),
    unknown subjects, and inactive accounts."""
    payload = decode_token(credentials.credentials, expected_type=ACCESS_TOKEN_TYPE)
    subject = payload.get("sub")
    if subject is None:
        raise InvalidTokenError()
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError() from exc

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise InvalidTokenError()
    if not user.is_active:
        raise InactiveUserError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory: allow only the given roles. Used by driver/ride routes
    in later steps (e.g. `Depends(require_role(UserRole.driver))`)."""

    async def _checker(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            from app.core.exceptions import PermissionDeniedError

            raise PermissionDeniedError(
                f"This action requires role(s): {', '.join(r.value for r in roles)}"
            )
        return current_user

    return _checker
