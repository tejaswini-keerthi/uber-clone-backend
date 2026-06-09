"""Surge pricing integration (cache-aside over the external surge API).

Flow for a zone's surge multiplier:
  1. Read Redis `surge:{geohash_zone}` (30s TTL). Hit -> return it.
  2. Miss -> GET http://surge-api:8001/surge/{geohash_zone}.
  3. On a 200, cache the multiplier with TTL and return it.
  4. On any failure (unreachable, non-200, bad body) -> return 1.0 (no surge)
     WITHOUT caching, so a transient outage isn't pinned for 30s.

Everything is async. The HTTP client can be injected for testing.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.redis import RedisCache

logger = logging.getLogger("app.pricing")

DEFAULT_SURGE_MULTIPLIER = 1.0


class PricingService:
    def __init__(
        self,
        redis: RedisCache | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.redis = redis
        self._client = http_client  # injected in tests; otherwise per-call client

    async def get_surge_multiplier(self, geohash_zone: str) -> float:
        """Cache-aside lookup of the surge multiplier for a pickup zone."""
        if self.redis is not None:
            cached = await self.redis.get_surge(geohash_zone)
            if cached is not None:
                return cached

        fetched = await self._fetch_from_api(geohash_zone)
        if fetched is None:
            return DEFAULT_SURGE_MULTIPLIER  # failure: don't cache the fallback

        if self.redis is not None:
            await self.redis.set_surge(
                geohash_zone, fetched, ttl_seconds=settings.surge_cache_ttl_seconds
            )
        return fetched

    async def _fetch_from_api(self, geohash_zone: str) -> float | None:
        """Return the multiplier from the surge API, or None on any failure."""
        url = f"{settings.surge_api_base_url}/surge/{geohash_zone}"
        try:
            if self._client is not None:
                resp = await self._client.get(url)
            else:
                async with httpx.AsyncClient(
                    timeout=settings.surge_request_timeout_seconds
                ) as client:
                    resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning(
                    "Surge API returned %s for zone %s; using no surge",
                    resp.status_code,
                    geohash_zone,
                )
                return None
            return float(resp.json()["surge_multiplier"])
        except Exception as exc:  # unreachable, timeout, bad JSON, missing key
            logger.warning(
                "Surge API unavailable for zone %s (%s); using no surge",
                geohash_zone,
                exc,
            )
            return None

    def compute_fare(self, distance_km: float, surge_multiplier: float) -> float:
        """Fare = (base_fare + distance_km * per_km_rate) * surge, 2 d.p."""
        fare = (settings.base_fare + distance_km * settings.per_km_rate) * surge_multiplier
        return round(fare, 2)
