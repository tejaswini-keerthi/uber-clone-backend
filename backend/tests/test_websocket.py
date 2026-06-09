"""WebSocket tests: ConnectionManager fan-out + live ride status over /ws."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_db, get_redis, get_session_factory
from app.core.redis import RedisCache
from app.core.websocket_manager import ConnectionManager
from app.main import app

AUTH = "/api/v1/auth"
DRIVERS = "/api/v1/drivers"
RIDES = "/api/v1/rides"


# --- ConnectionManager unit tests -------------------------------------------
class _FakeWS:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.accepted = False
        self.fail = fail

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("client gone")
        self.sent.append(message)


async def test_manager_connect_and_room_size():
    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect("ride-1", ws)
    assert ws.accepted
    assert mgr.room_size("ride-1") == 1


async def test_manager_broadcast_only_to_room():
    mgr = ConnectionManager()
    a, b, other = _FakeWS(), _FakeWS(), _FakeWS()
    await mgr.connect("ride-1", a)
    await mgr.connect("ride-1", b)
    await mgr.connect("ride-2", other)

    await mgr.broadcast("ride-1", {"hello": "world"})
    assert a.sent == [{"hello": "world"}]
    assert b.sent == [{"hello": "world"}]
    assert other.sent == []  # different room untouched


async def test_manager_disconnect_removes_room():
    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect("ride-1", ws)
    mgr.disconnect("ride-1", ws)
    assert mgr.room_size("ride-1") == 0


async def test_manager_prunes_dead_connections():
    mgr = ConnectionManager()
    good, dead = _FakeWS(), _FakeWS(fail=True)
    await mgr.connect("ride-1", good)
    await mgr.connect("ride-1", dead)
    await mgr.broadcast("ride-1", {"x": 1})
    # The failing socket is pruned; the healthy one still received the message.
    assert mgr.room_size("ride-1") == 1
    assert good.sent == [{"x": 1}]


# --- Integration over a real /ws connection ---------------------------------
@pytest.fixture
def ws_client(engine):
    """Sync TestClient (needed for WebSocket support) wired to the test engine.

    Redis is overridden to a non-connected no-op cache to avoid cross-loop use
    of the async `cache` fixture from TestClient's portal thread.
    """
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


def _online_driver(tc, email, lat, lng) -> dict:
    token = _register(tc, email, role="driver")
    headers = {"Authorization": f"Bearer {token}"}
    tc.post(DRIVERS, headers=headers, json={"vehicle_make": "T", "vehicle_model": "M", "vehicle_plate": "P"})
    tc.post(f"{DRIVERS}/me/location", headers=headers, json={"lat": lat, "lng": lng})
    tc.patch(f"{DRIVERS}/me/status", headers=headers, json={"status": "online"})
    return headers


def test_ws_rejects_without_token(ws_client):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/ws/{uuid.uuid4()}"):
            pass


def test_ws_rejects_invalid_token(ws_client):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/ws/{uuid.uuid4()}?token=not.a.jwt"):
            pass


def test_ws_snapshot_then_match_event(ws_client):
    rider_token = _register(ws_client, "wsrider@example.com")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    _online_driver(ws_client, "wsdriver@example.com", 37.7749, -122.4194)

    ride = ws_client.post(
        RIDES,
        headers=rider_headers,
        json={"pickup_lat": 37.7749, "pickup_lng": -122.4194, "dropoff_lat": 37.78, "dropoff_lng": -122.41},
    ).json()

    with ws_client.websocket_connect(f"/ws/{ride['id']}?token={rider_token}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["ride"]["status"] == "requested"

        # Trigger a state change over HTTP; the room should receive the event.
        ws_client.post(f"{RIDES}/{ride['id']}/match", headers=rider_headers)
        event = ws.receive_json()
        assert event["type"] == "ride_update"
        assert event["event"] == "matched"
        assert event["ride"]["driver_id"] is not None


def test_ws_non_participant_rejected(ws_client):
    rider_token = _register(ws_client, "owner@example.com")
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    ride = ws_client.post(
        RIDES,
        headers=rider_headers,
        json={"pickup_lat": 37.0, "pickup_lng": -122.0, "dropoff_lat": 37.1, "dropoff_lng": -122.1},
    ).json()

    intruder_token = _register(ws_client, "intruder@example.com")
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/ws/{ride['id']}?token={intruder_token}"):
            pass
