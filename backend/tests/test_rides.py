"""Ride lifecycle tests: request, authorization, and the state machine."""
from __future__ import annotations

import uuid

import pytest_asyncio

from app.repositories.driver_repository import DriverRepository
from app.services.ride_service import RideService

RIDES = "/api/v1/rides"
DRIVERS = "/api/v1/drivers"

_PICKUP = {"pickup_lat": 37.7750, "pickup_lng": -122.4195}
_DROPOFF = {"dropoff_lat": 37.7849, "dropoff_lng": -122.4094}
_RIDE_BODY = {**_PICKUP, **_DROPOFF}


async def _request_ride(client, headers, **overrides) -> dict:
    body = {**_RIDE_BODY, **overrides}
    resp = await client.post(RIDES, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def matched_ride(client, db, auth_headers, driver_profile) -> dict:
    """An online driver matched to a rider's requested ride (status=matched).

    Matching itself is built in step 6; here we drive `assign_driver` through the
    service directly so the lifecycle endpoints can be exercised end-to-end.
    """
    dheaders = driver_profile["headers"]
    await client.post(
        f"{DRIVERS}/me/location", headers=dheaders, json={"lat": 37.7749, "lng": -122.4194}
    )
    await client.patch(f"{DRIVERS}/me/status", headers=dheaders, json={"status": "online"})

    ride = await _request_ride(client, auth_headers)

    service = RideService(db)
    driver = await DriverRepository(db).get_by_id(uuid.UUID(driver_profile["driver"]["id"]))
    ride_obj = await service.rides.get_by_id(uuid.UUID(ride["id"]))
    await service.assign_driver(ride_obj, driver)
    await db.commit()

    return {
        "ride_id": ride["id"],
        "driver_id": driver_profile["driver"]["id"],
        "rider_headers": auth_headers,
        "driver_headers": dheaders,
    }


# --- Request -----------------------------------------------------------------
async def test_request_ride_creates_requested(client, auth_headers):
    body = await _request_ride(client, auth_headers)
    assert body["status"] == "requested"
    assert body["driver_id"] is None
    assert body["distance_km"] > 0
    assert body["estimated_fare"] > 0
    assert body["surge_multiplier"] == 1.0
    assert len(body["pickup_geohash"]) == 6


async def test_request_ride_requires_auth(client):
    resp = await client.post(RIDES, json=_RIDE_BODY)
    assert resp.status_code == 403


async def test_request_ride_invalid_coords_422(client, auth_headers):
    resp = await client.post(
        RIDES,
        headers=auth_headers,
        json={"pickup_lat": 999, "pickup_lng": 0, "dropoff_lat": 0, "dropoff_lng": 0},
    )
    assert resp.status_code == 422


async def test_request_ride_uses_default_city(client, auth_headers):
    body = await _request_ride(client, auth_headers)
    assert body["city"]  # default city applied


# --- Read / authorization ----------------------------------------------------
async def test_get_own_ride(client, auth_headers):
    ride = await _request_ride(client, auth_headers)
    resp = await client.get(f"{RIDES}/{ride['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == ride["id"]


async def test_get_ride_forbidden_for_non_participant(client, auth_headers, driver_headers):
    ride = await _request_ride(client, auth_headers)
    # The driver is not yet assigned, so not a participant.
    resp = await client.get(f"{RIDES}/{ride['id']}", headers=driver_headers)
    assert resp.status_code == 403


async def test_get_unknown_ride_404(client, auth_headers):
    resp = await client.get(
        f"{RIDES}/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_list_my_rides(client, auth_headers):
    await _request_ride(client, auth_headers)
    await _request_ride(client, auth_headers)
    resp = await client.get(RIDES, headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- State machine -----------------------------------------------------------
async def test_cancel_requested_ride(client, auth_headers):
    ride = await _request_ride(client, auth_headers)
    resp = await client.post(
        f"{RIDES}/{ride['id']}/cancel", headers=auth_headers, json={"reason": "changed mind"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "changed mind"
    assert body["cancelled_at"] is not None


async def test_cannot_start_unmatched_ride(client, auth_headers, driver_headers):
    ride = await _request_ride(client, auth_headers)
    resp = await client.post(f"{RIDES}/{ride['id']}/start", headers=driver_headers)
    assert resp.status_code == 409  # no assigned driver


async def test_assign_driver_marks_driver_busy(client, matched_ride):
    resp = await client.get(f"{DRIVERS}/me", headers=matched_ride["driver_headers"])
    assert resp.json()["status"] == "on_trip"


async def test_full_lifecycle_start_then_complete(client, matched_ride):
    rid = matched_ride["ride_id"]
    dheaders = matched_ride["driver_headers"]

    started = await client.post(f"{RIDES}/{rid}/start", headers=dheaders)
    assert started.status_code == 200
    assert started.json()["status"] == "on_trip"
    assert started.json()["started_at"] is not None

    completed = await client.post(f"{RIDES}/{rid}/complete", headers=dheaders)
    assert completed.status_code == 200
    body = completed.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["final_fare"] == body["estimated_fare"]


async def test_completing_frees_driver(client, matched_ride):
    rid = matched_ride["ride_id"]
    dheaders = matched_ride["driver_headers"]
    await client.post(f"{RIDES}/{rid}/start", headers=dheaders)
    await client.post(f"{RIDES}/{rid}/complete", headers=dheaders)
    resp = await client.get(f"{DRIVERS}/me", headers=dheaders)
    assert resp.json()["status"] == "online"


async def test_only_assigned_driver_can_start(client, matched_ride):
    # Rider tries to start their own ride -> forbidden (driver-only action).
    resp = await client.post(
        f"{RIDES}/{matched_ride['ride_id']}/start", headers=matched_ride["rider_headers"]
    )
    assert resp.status_code == 403


async def test_cannot_complete_before_starting(client, matched_ride):
    # Ride is `matched`, not `on_trip`.
    resp = await client.post(
        f"{RIDES}/{matched_ride['ride_id']}/complete",
        headers=matched_ride["driver_headers"],
    )
    assert resp.status_code == 409


async def test_cancel_matched_ride_frees_driver(client, matched_ride):
    rid = matched_ride["ride_id"]
    resp = await client.post(
        f"{RIDES}/{rid}/cancel", headers=matched_ride["rider_headers"], json={}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    driver = await client.get(f"{DRIVERS}/me", headers=matched_ride["driver_headers"])
    assert driver.json()["status"] == "online"


async def test_cannot_cancel_completed_ride(client, matched_ride):
    rid = matched_ride["ride_id"]
    dheaders = matched_ride["driver_headers"]
    await client.post(f"{RIDES}/{rid}/start", headers=dheaders)
    await client.post(f"{RIDES}/{rid}/complete", headers=dheaders)
    resp = await client.post(
        f"{RIDES}/{rid}/cancel", headers=matched_ride["rider_headers"], json={}
    )
    assert resp.status_code == 409  # completed is terminal
