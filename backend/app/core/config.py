"""Application settings loaded from environment via pydantic-settings.

All configuration flows through this single Settings object so that the rest of
the codebase never reads os.environ directly. Import the cached `settings`
singleton (via `get_settings()`), never instantiate Settings yourself.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_name: str = "uber-clone-backend"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- Database (PostgreSQL + PostGIS) ---
    postgres_user: str = "uber"
    postgres_password: str = "uber"
    postgres_db: str = "uber"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    # Optional full override (e.g. tests use sqlite+aiosqlite). When set it wins.
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # --- JWT / Auth ---
    jwt_secret_key: str = "change-me-in-production-please-use-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # --- Kafka ---
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_ride_requests_topic: str = "ride-requests"
    kafka_enabled: bool = True

    # --- Pricing engine (surge) ---
    surge_api_base_url: str = "http://surge-api:8001"
    surge_request_timeout_seconds: float = 2.0
    surge_cache_ttl_seconds: int = 30
    # Fare = (base_fare + distance_km * per_km_rate) * surge_multiplier
    base_fare: float = 2.50
    per_km_rate: float = 1.20

    # --- Geo / matching ---
    geohash_precision: int = 6
    driver_search_radius_meters: int = 5000
    default_city: str = "San Francisco"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL. Honors DATABASE_URL override when present."""
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Patchable in tests via dependency override."""
    return Settings()


settings = get_settings()
