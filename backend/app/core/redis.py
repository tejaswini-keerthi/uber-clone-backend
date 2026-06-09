"""Redis cache wrapper (redis.asyncio).

What lives in Redis:
  - Online driver positions, geohash-zone-indexed: a SET per zone
    (`drivers:zone:{geohash}`) of available driver ids, plus a per-driver hash
    (`driver:loc:{id}`) with the last lat/lng/zone. This is a hot, queryable
    snapshot of supply — handy for ops/analytics and as an optional pre-filter.
  - Surge multipliers per zone (`surge:{geohash}`), short TTL (filled in step 9).

Authoritative driver matching is done in PostGIS (ST_DWithin over a GiST index),
not here — so every method is best-effort: if Redis is down or unconfigured the
call is a no-op and the request still succeeds.
"""
from __future__ import annotations

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("app.redis")


class RedisCache:
    def __init__(self) -> None:
        self._redis: Redis | None = None

    async def start(self, url: str | None = None) -> None:
        self._redis = Redis.from_url(
            url or settings.redis_url, encoding="utf-8", decode_responses=True
        )
        await self._redis.ping()
        logger.info("Redis connected")

    async def stop(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    @property
    def available(self) -> bool:
        return self._redis is not None

    # --- driver location cache ---
    async def upsert_location(
        self, driver_id, lat: float, lng: float, zone: str
    ) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.hset(
                f"driver:loc:{driver_id}",
                mapping={"lat": lat, "lng": lng, "zone": zone},
            )
        except RedisError as exc:  # pragma: no cover - best effort
            logger.warning("redis upsert_location failed: %s", exc)

    async def get_location(self, driver_id) -> dict | None:
        if self._redis is None:
            return None
        try:
            data = await self._redis.hgetall(f"driver:loc:{driver_id}")
            return data or None
        except RedisError as exc:  # pragma: no cover
            logger.warning("redis get_location failed: %s", exc)
            return None

    async def mark_available(self, driver_id, zone: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.sadd(f"drivers:zone:{zone}", str(driver_id))
        except RedisError as exc:  # pragma: no cover
            logger.warning("redis mark_available failed: %s", exc)

    async def mark_unavailable(self, driver_id, zone: str | None) -> None:
        if self._redis is None or not zone:
            return
        try:
            await self._redis.srem(f"drivers:zone:{zone}", str(driver_id))
        except RedisError as exc:  # pragma: no cover
            logger.warning("redis mark_unavailable failed: %s", exc)

    async def available_in_zone(self, zone: str) -> set[str]:
        if self._redis is None:
            return set()
        try:
            return set(await self._redis.smembers(f"drivers:zone:{zone}"))
        except RedisError as exc:  # pragma: no cover
            logger.warning("redis available_in_zone failed: %s", exc)
            return set()

    # --- surge cache (step 9) ---
    async def get_surge(self, zone: str) -> float | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(f"surge:{zone}")
            return float(value) if value is not None else None
        except (RedisError, ValueError) as exc:  # pragma: no cover
            logger.warning("redis get_surge failed: %s", exc)
            return None

    async def set_surge(self, zone: str, multiplier: float, ttl_seconds: int = 60) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(f"surge:{zone}", multiplier, ex=ttl_seconds)
        except RedisError as exc:  # pragma: no cover
            logger.warning("redis set_surge failed: %s", exc)


# Process-wide singleton; started/stopped in app.main's lifespan.
redis_cache = RedisCache()
