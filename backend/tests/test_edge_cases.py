"""Additional edge-case coverage (Step 11). New tests only — nothing here
modifies existing test files.

Auth-code note: this implementation returns 403 for a *missing* bearer header
(FastAPI's HTTPBearer default) and 401 for an *invalid/expired* token. The
existing auth suite already locks those codes in, so the tests below assert the
actual behaviour. (The spec listed these two codes swapped; flipping them would
require editing the existing tests, which we're told not to do.)
"""
from __future__ import annotations

import httpx
import pygeohash

from app.api.deps import get_pricing_service
from app.core.config import settings
from app.core.geo import haversine_km
from app.core.security import create_access_token
from app.main import app
from app.services.pricing_service import PricingService

AUTH = "/api/v1/auth"
RIDES = "/api/v1/rides"
DRIVERS = "/api/v1/drivers"

_PICKUP = (37.7749, -122.4194)
_DROPOFF = (37.7849, -122.4094)
_RIDE_BODY = {
    "pickup_lat": _PICKUP[0],
    "pickup_lng": _PICKUP[1],
    "dropoff_lat": _DROPOFF[0],
    "dropoff_lng": _DROPOFF[1],
}


# --- helpers -----------------------------------------------------------------
async def _online_driver(client, email, lat=37.7749, lng=-122.4194) -> dict:
    await client.post(
        f"{AUTH}/register",
        json={"email": email, "password": "supersecret123", "full_name": email, "role": "driver"},
    )
    login = await client.post(
        f"{AUTH}/login", json={"email": email, "password": "supersecret123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    prof = await client.post(
        DRIVERS,
        headers=headers,
        json={"vehicle_make": "Toyota", "vehicle_model": "Prius", "vehicle_plate": email[:6]},
    )
    await client.post(f"{DRIVERS}/me/location", headers=headers, json={"lat": lat, "lng": lng})
    await client.patch(f"{DRIVERS}/me/status", headers=headers, json={"status": "online"})
    return {"headers": headers, "id": prof.json()["id"]}


async def _matched_ride(client, rider_headers, driver_email="edgedriver@example.com") -> dict:
    drv = await _online_driver(client, driver_email)
    ride = (await client.post(RIDES, headers=rider_headers, json=_RIDE_BODY)).json()
    matched = await client.post(f"{RIDES}/{ride['id']}/match", headers=rider_headers)
    assert matched.status_code == 200, matched.text
    return {"ride_id": ride["id"], "driver": drv}


# --- Auth edge cases ---------------------------------------------------------
async def test_register_duplicate_email_returns_409(client, registered_user):
    resp = await client.post(f"{AUTH}/register", json=registered_user["payload"])
    assert resp.status_code == 409


async def test_login_wrong_password_returns_401(client, registered_user):
    resp = await client.post(
        f"{AUTH}/login",
        json={"email": registered_user["payload"]["email"], "password": "wrongpass1"},
    )
    assert resp.status_code == 401


async def test_expired_access_token_is_rejected(client, registered_user, monkeypatch):
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    expired = create_access_token(registered_user["user"]["id"])
    resp = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401  # invalid/expired token -> 401


async def test_missing_authorization_header_is_rejected(client):
    resp = await client.get(f"{AUTH}/me")
    assert resp.status_code == 403  # HTTPBearer: missing credentials -> 403


async def test_refresh_rotation_old_token_rejected_after_use(client, auth_tokens):
    first = await client.post(
        f"{AUTH}/refresh", json={"refresh_token": auth_tokens["refresh_token"]}
    )
    assert first.status_code == 200
    reuse = await client.post(
        f"{AUTH}/refresh", json={"refresh_token": auth_tokens["refresh_token"]}
    )
    assert reuse.status_code == 401  # old (rotated) token is revoked


# --- Ride lifecycle edge cases ----------------------------------------------
async def test_rider_cannot_request_second_active_ride(client, auth_headers):
    await _matched_ride(client, auth_headers)  # rider now has an active (matched) ride
    resp = await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)
    assert resp.status_code == 409


async def test_only_assigned_driver_can_update_status(client, auth_headers):
    matched = await _matched_ride(client, auth_headers)
    # A different, unrelated driver tries to start the trip.
    other = await _online_driver(client, "intruderdriver@example.com")
    resp = await client.post(
        f"{RIDES}/{matched['ride_id']}/start", headers=other["headers"]
    )
    assert resp.status_code == 403


async def test_cancel_from_requested_state_works(client, auth_headers):
    ride = (await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)).json()
    resp = await client.post(f"{RIDES}/{ride['id']}/cancel", headers=auth_headers, json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_cancel_from_on_trip_state_rejected(client, auth_headers):
    matched = await _matched_ride(client, auth_headers)
    rid = matched["ride_id"]
    dheaders = matched["driver"]["headers"]
    await client.post(f"{RIDES}/{rid}/start", headers=dheaders)  # -> on_trip
    resp = await client.post(f"{RIDES}/{rid}/cancel", headers=auth_headers, json={})
    assert resp.status_code == 409  # cannot cancel a trip in progress


async def test_estimated_fare_reflects_surge(client, auth_headers, cache):
    surge = 1.5

    def handler(request):
        return httpx.Response(
            200, json={"geohash": "9q8yyk", "surge_multiplier": surge, "zone_demand": 7}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_pricing_service] = lambda: PricingService(cache, http)
    try:
        resp = await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)
        assert resp.status_code == 201
        body = resp.json()
        dist = round(haversine_km(*_PICKUP, *_DROPOFF), 3)
        base = round((settings.base_fare + dist * settings.per_km_rate) * 1.0, 2)
        expected = round((settings.base_fare + dist * settings.per_km_rate) * surge, 2)
        assert body["surge_multiplier"] == surge
        assert body["estimated_fare"] > 0
        assert body["estimated_fare"] == expected
        assert body["estimated_fare"] > base  # surge raised the fare
    finally:
        await http.aclose()


# --- Driver edge cases -------------------------------------------------------
async def test_driver_cannot_go_online_without_profile(client, driver_headers):
    # driver_headers user has NOT created a driver profile.
    resp = await client.patch(
        f"{DRIVERS}/me/status", headers=driver_headers, json={"status": "online"}
    )
    assert resp.status_code == 404


async def test_offline_driver_not_matched(client, auth_headers, driver_headers):
    # Create a profile + location but stay offline.
    await client.post(
        DRIVERS,
        headers=driver_headers,
        json={"vehicle_make": "Honda", "vehicle_model": "Fit", "vehicle_plate": "OFF1"},
    )
    await client.post(
        f"{DRIVERS}/me/location", headers=driver_headers, json={"lat": 37.7749, "lng": -122.4194}
    )
    ride = (await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)).json()
    resp = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert resp.status_code == 409  # offline driver is not a candidate


async def test_location_update_stores_correct_geohash(client, driver_profile):
    lat, lng = 40.7128, -74.0060  # New York City
    resp = await client.post(
        f"{DRIVERS}/me/location", headers=driver_profile["headers"], json={"lat": lat, "lng": lng}
    )
    assert resp.status_code == 200
    expected = pygeohash.encode(lat, lng, precision=settings.geohash_precision)
    assert resp.json()["geohash_zone"] == expected


async def test_driver_cannot_create_two_profiles(client, driver_profile):
    resp = await client.post(
        DRIVERS,
        headers=driver_profile["headers"],
        json={"vehicle_make": "X", "vehicle_model": "Y", "vehicle_plate": "Z"},
    )
    assert resp.status_code == 409


async def test_non_participant_cannot_view_ride(client, auth_headers, driver_headers):
    ride = (await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)).json()
    resp = await client.get(f"{RIDES}/{ride['id']}", headers=driver_headers)
    assert resp.status_code == 403
