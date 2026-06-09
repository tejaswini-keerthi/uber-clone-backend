"""Additional WebSocket edge-case coverage (Step 11). New tests only."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_db, get_pricing_service, get_redis, get_session_factory
from app.core.redis import RedisCache
from app.core.websocket_manager import manager
from app.main import app
from app.services.pricing_service import PricingService

AUTH = "/api/v1/auth"
DRIVERS = "/api/v1/drivers"
RIDES = "/api/v1/rides"

_RIDE_BODY = {
    "pickup_lat": 37.7749,
    "pickup_lng": -122.4194,
    "dropoff_lat": 37.7849,
    "dropoff_lng": -122.4094,
}


class _NoSurgePricing(PricingService):
    async def get_surge_multiplier(self, geohash_zone: str) -> float:
        return 1.0


@pytest.fixture
def ws_client(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_redis] = lambda: RedisCache()
    app.dependency_overrides[get_pricing_service] = lambda: _NoSurgePricing()
    client = TestClient(app)
    yield client
    client.close()
    app.dependency_overrides.clear()


def _register(tc, email, role=None) -> str:
    payload = {"email": email, "password": "supersecret123", "full_name": email}
    if role:
        payload["role"] = role
    tc.post(f"{AUTH}/register", json=payload)
    resp = tc.post(f"{AUTH}/login", json={"email": email, "password": "supersecret123"})
    return resp.json()["access_token"]


def _online_driver(tc, email, lat=37.7749, lng=-122.4194) -> str:
    token = _register(tc, email, role="driver")
    headers = {"Authorization": f"Bearer {token}"}
    tc.post(DRIVERS, headers=headers, json={"vehicle_make": "T", "vehicle_model": "M", "vehicle_plate": "P"})
    tc.post(f"{DRIVERS}/me/location", headers=headers, json={"lat": lat, "lng": lng})
    tc.patch(f"{DRIVERS}/me/status", headers=headers, json={"status": "online"})
    return token


def test_ws_third_user_cannot_connect(ws_client):
    rider_token = _register(ws_client, "wsowner@example.com")
    ride = ws_client.post(
        RIDES, headers={"Authorization": f"Bearer {rider_token}"}, json=_RIDE_BODY
    ).json()
    third_token = _register(ws_client, "wsthird@example.com")
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/ws/{ride['id']}?token={third_token}"):
            pass


def test_ws_client_pruned_on_disconnect(ws_client):
    rider_token = _register(ws_client, "wsprune@example.com")
    ride = ws_client.post(
        RIDES, headers={"Authorization": f"Bearer {rider_token}"}, json=_RIDE_BODY
    ).json()
    room = str(ride["id"])

    with ws_client.websocket_connect(f"/ws/{ride['id']}?token={rider_token}") as ws:
        ws.receive_json()  # snapshot
        assert manager.room_size(room) == 1

    # After the socket closes, the server prunes it from the room.
    for _ in range(20):
        if manager.room_size(room) == 0:
            break
        time.sleep(0.05)
    assert manager.room_size(room) == 0


def test_ws_all_state_transitions_broadcast(ws_client):
    rider_token = _register(ws_client, "wsflow@example.com")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    driver_token = _online_driver(ws_client, "wsflowdriver@example.com")
    driver_headers = {"Authorization": f"Bearer {driver_token}"}

    ride = ws_client.post(RIDES, headers=rider_headers, json=_RIDE_BODY).json()
    rid = ride["id"]

    with ws_client.websocket_connect(f"/ws/{rid}?token={rider_token}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["ride"]["status"] == "requested"

        ws_client.post(f"{RIDES}/{rid}/match", headers=rider_headers)
        assert _next_event(ws) == "matched"

        ws_client.post(f"{RIDES}/{rid}/start", headers=driver_headers)
        assert _next_event(ws) == "on_trip"

        ws_client.post(f"{RIDES}/{rid}/complete", headers=driver_headers)
        assert _next_event(ws) == "completed"


def test_ws_cancelled_transition_broadcast(ws_client):
    rider_token = _register(ws_client, "wscancel@example.com")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    ride = ws_client.post(RIDES, headers=rider_headers, json=_RIDE_BODY).json()
    rid = ride["id"]

    with ws_client.websocket_connect(f"/ws/{rid}?token={rider_token}") as ws:
        ws.receive_json()  # snapshot
        ws_client.post(f"{RIDES}/{rid}/cancel", headers=rider_headers, json={})
        assert _next_event(ws) == "cancelled"


def test_ws_assigned_driver_can_connect(ws_client):
    rider_token = _register(ws_client, "wsrider2@example.com")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    driver_token = _online_driver(ws_client, "wsassigned@example.com")
    ride = ws_client.post(RIDES, headers=rider_headers, json=_RIDE_BODY).json()
    ws_client.post(f"{RIDES}/{ride['id']}/match", headers=rider_headers)

    # The assigned driver is a participant and may subscribe.
    with ws_client.websocket_connect(f"/ws/{ride['id']}?token={driver_token}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["ride"]["status"] == "matched"


def _next_event(ws) -> str:
    """Read messages until a ride_update arrives; return its event name."""
    for _ in range(5):
        msg = ws.receive_json()
        if msg.get("type") == "ride_update":
            return msg["event"]
    raise AssertionError("no ride_update event received")
