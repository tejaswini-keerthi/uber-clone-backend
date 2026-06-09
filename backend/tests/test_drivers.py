"""Driver profile, availability toggle, and location update tests."""
from __future__ import annotations

DRIVERS = "/api/v1/drivers"


# --- Profile creation --------------------------------------------------------
async def test_create_driver_profile(client, driver_headers):
    resp = await client.post(
        DRIVERS,
        headers=driver_headers,
        json={
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "vehicle_plate": "XYZ789",
            "vehicle_color": "Blue",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["vehicle_make"] == "Honda"
    assert body["status"] == "offline"
    assert body["rating"] == 5.0
    assert body["current_lat"] is None


async def test_rider_cannot_create_driver_profile(client, auth_headers):
    # auth_headers belongs to a rider-role user.
    resp = await client.post(
        DRIVERS,
        headers=auth_headers,
        json={"vehicle_make": "A", "vehicle_model": "B", "vehicle_plate": "C"},
    )
    assert resp.status_code == 403


async def test_create_driver_profile_twice_conflicts(client, driver_profile):
    resp = await client.post(
        DRIVERS,
        headers=driver_profile["headers"],
        json={"vehicle_make": "A", "vehicle_model": "B", "vehicle_plate": "C"},
    )
    assert resp.status_code == 409


async def test_create_driver_profile_requires_auth(client):
    resp = await client.post(
        DRIVERS, json={"vehicle_make": "A", "vehicle_model": "B", "vehicle_plate": "C"}
    )
    assert resp.status_code == 403


# --- Get profile -------------------------------------------------------------
async def test_get_my_driver_profile(client, driver_profile):
    resp = await client.get(f"{DRIVERS}/me", headers=driver_profile["headers"])
    assert resp.status_code == 200
    assert resp.json()["id"] == driver_profile["driver"]["id"]


async def test_get_my_driver_profile_when_none_404(client, driver_headers):
    # driver_headers user exists but has NOT created a profile.
    resp = await client.get(f"{DRIVERS}/me", headers=driver_headers)
    assert resp.status_code == 404


async def test_get_driver_by_id(client, driver_profile):
    driver_id = driver_profile["driver"]["id"]
    resp = await client.get(f"{DRIVERS}/{driver_id}", headers=driver_profile["headers"])
    assert resp.status_code == 200
    assert resp.json()["id"] == driver_id


async def test_get_unknown_driver_404(client, driver_profile):
    resp = await client.get(
        f"{DRIVERS}/00000000-0000-0000-0000-000000000000",
        headers=driver_profile["headers"],
    )
    assert resp.status_code == 404


# --- Location update ---------------------------------------------------------
async def test_update_location_sets_geohash(client, driver_profile):
    resp = await client.post(
        f"{DRIVERS}/me/location",
        headers=driver_profile["headers"],
        json={"lat": 37.7749, "lng": -122.4194},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_lat"] == 37.7749
    assert body["current_lng"] == -122.4194
    assert body["geohash_zone"] is not None
    assert len(body["geohash_zone"]) == 6  # configured precision
    assert body["last_location_update"] is not None


async def test_update_location_validates_bounds(client, driver_profile):
    resp = await client.post(
        f"{DRIVERS}/me/location",
        headers=driver_profile["headers"],
        json={"lat": 200.0, "lng": 0.0},
    )
    assert resp.status_code == 422


async def test_update_location_without_profile_404(client, driver_headers):
    resp = await client.post(
        f"{DRIVERS}/me/location",
        headers=driver_headers,
        json={"lat": 37.0, "lng": -122.0},
    )
    assert resp.status_code == 404


# --- Status toggle -----------------------------------------------------------
async def test_go_online_requires_location_first(client, driver_profile):
    resp = await client.patch(
        f"{DRIVERS}/me/status",
        headers=driver_profile["headers"],
        json={"status": "online"},
    )
    assert resp.status_code == 409  # no location yet


async def test_go_online_after_location(client, driver_profile):
    await client.post(
        f"{DRIVERS}/me/location",
        headers=driver_profile["headers"],
        json={"lat": 37.7749, "lng": -122.4194},
    )
    resp = await client.patch(
        f"{DRIVERS}/me/status",
        headers=driver_profile["headers"],
        json={"status": "online"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "online"


async def test_toggle_offline(client, driver_profile):
    await client.post(
        f"{DRIVERS}/me/location",
        headers=driver_profile["headers"],
        json={"lat": 37.7749, "lng": -122.4194},
    )
    await client.patch(
        f"{DRIVERS}/me/status",
        headers=driver_profile["headers"],
        json={"status": "online"},
    )
    resp = await client.patch(
        f"{DRIVERS}/me/status",
        headers=driver_profile["headers"],
        json={"status": "offline"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "offline"


async def test_cannot_set_on_trip_via_status_endpoint(client, driver_profile):
    resp = await client.patch(
        f"{DRIVERS}/me/status",
        headers=driver_profile["headers"],
        json={"status": "on_trip"},
    )
    assert resp.status_code == 409
