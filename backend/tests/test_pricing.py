"""Surge pricing tests: cache-aside, failure fallback, and fare application."""
from __future__ import annotations

import httpx

from app.api.deps import get_pricing_service
from app.core.config import settings
from app.core.geo import haversine_km
from app.main import app
from app.services.pricing_service import PricingService

RIDES = "/api/v1/rides"
_ZONE = "9q8yyk"


def _mock_client(handler) -> httpx.AsyncClient:
    """An httpx client whose requests are served by `handler` (no network)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- compute_fare ------------------------------------------------------------
def test_compute_fare_formula():
    svc = PricingService()
    # (2.50 + 10 * 1.20) * 1.5 = (2.50 + 12.0) * 1.5 = 21.75
    assert svc.compute_fare(10.0, 1.5) == 21.75
    # No surge
    assert svc.compute_fare(10.0, 1.0) == 14.50


# --- cache-aside -------------------------------------------------------------
async def test_surge_cache_miss_then_hit(cache):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json={"geohash": _ZONE, "surge_multiplier": 1.8, "zone_demand": 42}
        )

    async with _mock_client(handler) as http:
        svc = PricingService(redis=cache, http_client=http)

        # Miss -> calls API, returns 1.8, writes to Redis.
        assert await svc.get_surge_multiplier(_ZONE) == 1.8
        assert calls["n"] == 1
        assert await cache.get_surge(_ZONE) == 1.8

        # Hit -> served from Redis, API not called again.
        assert await svc.get_surge_multiplier(_ZONE) == 1.8
        assert calls["n"] == 1


async def test_surge_non_200_defaults_and_not_cached(cache):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    async with _mock_client(handler) as http:
        svc = PricingService(redis=cache, http_client=http)
        assert await svc.get_surge_multiplier(_ZONE) == 1.0
        # Failure is not cached (so we retry next time).
        assert await cache.get_surge(_ZONE) is None


async def test_surge_unreachable_defaults_and_not_cached(cache):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("surge-api unreachable")

    async with _mock_client(handler) as http:
        svc = PricingService(redis=cache, http_client=http)
        assert await svc.get_surge_multiplier(_ZONE) == 1.0
        assert await cache.get_surge(_ZONE) is None


async def test_surge_calls_correct_url(cache):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"geohash": _ZONE, "surge_multiplier": 2.0, "zone_demand": 5}
        )

    async with _mock_client(handler) as http:
        svc = PricingService(redis=cache, http_client=http)
        await svc.get_surge_multiplier(_ZONE)
    assert seen["url"] == f"{settings.surge_api_base_url}/surge/{_ZONE}"


# --- integration: surge applied to the stored/returned fare ------------------
async def test_request_ride_applies_surge_to_fare(client, auth_headers, cache):
    surge = 2.0

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"geohash": _ZONE, "surge_multiplier": surge, "zone_demand": 9}
        )

    http = _mock_client(handler)
    # Override the conftest default for this test; the client fixture clears all
    # overrides on teardown.
    app.dependency_overrides[get_pricing_service] = lambda: PricingService(cache, http)
    try:
        pickup = (37.7749, -122.4194)
        dropoff = (37.7849, -122.4094)
        resp = await client.post(
            RIDES,
            headers=auth_headers,
            json={
                "pickup_lat": pickup[0],
                "pickup_lng": pickup[1],
                "dropoff_lat": dropoff[0],
                "dropoff_lng": dropoff[1],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()

        dist_km = round(haversine_km(*pickup, *dropoff), 3)
        expected = round((settings.base_fare + dist_km * settings.per_km_rate) * surge, 2)
        assert body["surge_multiplier"] == surge
        assert body["estimated_fare"] == expected
    finally:
        await http.aclose()
