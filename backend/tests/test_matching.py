"""Driver-matching tests: PostGIS nearest-driver query + Redis zone cache."""
from __future__ import annotations

from app.core.geo import encode_geohash

RIDES = "/api/v1/rides"
DRIVERS = "/api/v1/drivers"
AUTH = "/api/v1/auth"

_PICKUP = (37.7749, -122.4194)
_DROPOFF = (37.7849, -122.4094)


async def _make_online_driver(client, email, lat, lng) -> dict:
    reg = await client.post(
        f"{AUTH}/register",
        json={"email": email, "password": "supersecret123", "full_name": email, "role": "driver"},
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        f"{AUTH}/login", json={"email": email, "password": "supersecret123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    prof = await client.post(
        DRIVERS,
        headers=headers,
        json={"vehicle_make": "Toyota", "vehicle_model": "X", "vehicle_plate": email[:6]},
    )
    assert prof.status_code == 201, prof.text
    await client.post(f"{DRIVERS}/me/location", headers=headers, json={"lat": lat, "lng": lng})
    st = await client.patch(f"{DRIVERS}/me/status", headers=headers, json={"status": "online"})
    assert st.status_code == 200, st.text
    return {"headers": headers, "id": prof.json()["id"]}


async def _make_rider(client, email) -> dict:
    await client.post(
        f"{AUTH}/register",
        json={"email": email, "password": "supersecret123", "full_name": email},
    )
    login = await client.post(
        f"{AUTH}/login", json={"email": email, "password": "supersecret123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _request_ride(client, headers) -> dict:
    body = {
        "pickup_lat": _PICKUP[0],
        "pickup_lng": _PICKUP[1],
        "dropoff_lat": _DROPOFF[0],
        "dropoff_lng": _DROPOFF[1],
    }
    resp = await client.post(RIDES, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Matching ----------------------------------------------------------------
async def test_match_assigns_nearest_driver(client, auth_headers):
    near = await _make_online_driver(client, "near@example.com", 37.7749, -122.4194)
    await _make_online_driver(client, "far@example.com", 37.7760, -122.4170)  # ~250m
    ride = await _request_ride(client, auth_headers)

    resp = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "matched"
    assert body["driver_id"] == near["id"]
    assert body["matched_at"] is not None


async def test_match_no_drivers_returns_409(client, auth_headers):
    ride = await _request_ride(client, auth_headers)
    resp = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert resp.status_code == 409


async def test_offline_driver_not_matched(client, auth_headers, driver_profile):
    # driver_profile exists but never went online.
    ride = await _request_ride(client, auth_headers)
    resp = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert resp.status_code == 409


async def test_match_marks_driver_busy(client, auth_headers):
    drv = await _make_online_driver(client, "busy@example.com", 37.7749, -122.4194)
    ride = await _request_ride(client, auth_headers)
    await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    resp = await client.get(f"{DRIVERS}/me", headers=drv["headers"])
    assert resp.json()["status"] == "on_trip"


async def test_match_requires_requested_state(client, auth_headers):
    await _make_online_driver(client, "once@example.com", 37.7749, -122.4194)
    ride = await _request_ride(client, auth_headers)
    first = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert first.status_code == 200
    second = await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert second.status_code == 409  # already matched


async def test_only_rider_can_match(client, auth_headers):
    await _make_online_driver(client, "drv2@example.com", 37.7749, -122.4194)
    ride = await _request_ride(client, auth_headers)
    other = await _make_rider(client, "other@example.com")
    resp = await client.post(f"{RIDES}/{ride['id']}/match", headers=other)
    assert resp.status_code == 403


# --- Redis zone cache --------------------------------------------------------
async def test_online_driver_indexed_in_redis_zone(client, cache):
    lat, lng = 37.7749, -122.4194
    drv = await _make_online_driver(client, "zone@example.com", lat, lng)
    zone = encode_geohash(lat, lng)
    members = await cache.available_in_zone(zone)
    assert drv["id"] in members


async def test_offline_removes_driver_from_redis_zone(client, cache):
    lat, lng = 37.7749, -122.4194
    drv = await _make_online_driver(client, "off@example.com", lat, lng)
    zone = encode_geohash(lat, lng)
    await client.patch(
        f"{DRIVERS}/me/status", headers=drv["headers"], json={"status": "offline"}
    )
    members = await cache.available_in_zone(zone)
    assert drv["id"] not in members


async def test_match_removes_driver_from_redis_zone(client, auth_headers, cache):
    lat, lng = 37.7749, -122.4194
    drv = await _make_online_driver(client, "match-redis@example.com", lat, lng)
    zone = encode_geohash(lat, lng)
    assert drv["id"] in await cache.available_in_zone(zone)

    ride = await _request_ride(client, auth_headers)
    await client.post(f"{RIDES}/{ride['id']}/match", headers=auth_headers)
    assert drv["id"] not in await cache.available_in_zone(zone)
