"""Kafka producer tests: event schema, topic, publish-after-commit, graceful degrade."""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest_asyncio

from app.api.deps import get_kafka
from app.core.kafka import KafkaPublisher
from app.main import app
from app.models.ride import Ride
from app.schemas.ride import RideRequestEvent

RIDES = "/api/v1/rides"

_EXPECTED_KEYS = {
    "event_id",
    "ride_id",
    "rider_id",
    "pickup_lat",
    "pickup_lng",
    "pickup_geohash",
    "dropoff_lat",
    "dropoff_lng",
    "timestamp",
    "city",
}
_RIDE_BODY = {
    "pickup_lat": 37.7749,
    "pickup_lng": -122.4194,
    "dropoff_lat": 37.7849,
    "dropoff_lng": -122.4094,
}


class _RecordingPublisher:
    """Stand-in for KafkaPublisher that records published events."""

    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish_ride_request(self, event: dict) -> None:
        self.published.append(event)


class _FakeProducer:
    """Stand-in for AIOKafkaProducer to inspect topic/key/value."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def send_and_wait(self, topic, value=None, key=None) -> None:
        self.calls.append((topic, value, key))


@pytest_asyncio.fixture
async def recorder():
    rec = _RecordingPublisher()
    app.dependency_overrides[get_kafka] = lambda: rec
    yield rec
    app.dependency_overrides.pop(get_kafka, None)


# --- Unit: event schema ------------------------------------------------------
def test_event_from_ride_has_exact_schema():
    ride = Ride(
        id=uuid.uuid4(),
        rider_id=uuid.uuid4(),
        pickup_lat=37.7749,
        pickup_lng=-122.4194,
        pickup_geohash="9q8yyk",
        dropoff_lat=37.7849,
        dropoff_lng=-122.4094,
        city="San Francisco",
    )
    event = RideRequestEvent.from_ride(ride).model_dump(mode="json")
    assert set(event.keys()) == _EXPECTED_KEYS
    # types per the contract
    assert isinstance(event["event_id"], str) and uuid.UUID(event["event_id"])
    assert event["ride_id"] == str(ride.id)
    assert event["rider_id"] == str(ride.rider_id)
    assert isinstance(event["pickup_lat"], float)
    assert event["pickup_geohash"] == "9q8yyk"
    assert event["city"] == "San Francisco"
    # timestamp is ISO-8601 parseable
    datetime.fromisoformat(event["timestamp"])


# --- Unit: producer publishes to the right topic -----------------------------
async def test_publisher_uses_ride_requests_topic():
    pub = KafkaPublisher()
    pub._producer = _FakeProducer()  # inject fake, bypass real broker
    event = {"event_id": "e", "ride_id": "r-123"}
    await pub.publish_ride_request(event)
    topic, value, key = pub._producer.calls[0]
    assert topic == "ride-requests"
    assert value == event
    assert key == "r-123"  # keyed by ride_id


async def test_publisher_noop_when_unavailable():
    pub = KafkaPublisher()  # no producer started
    assert pub.available is False
    # Must not raise even though Kafka is unavailable.
    await pub.publish_ride_request({"event_id": "x", "ride_id": "y"})


# --- Integration -------------------------------------------------------------
async def test_request_ride_publishes_event(client, auth_headers, recorder):
    resp = await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)
    assert resp.status_code == 201, resp.text
    assert len(recorder.published) == 1

    event = recorder.published[0]
    assert set(event.keys()) == _EXPECTED_KEYS
    assert event["ride_id"] == resp.json()["id"]
    assert event["pickup_geohash"] == resp.json()["pickup_geohash"]
    assert len(event["pickup_geohash"]) == 6
    datetime.fromisoformat(event["timestamp"])


async def test_invalid_request_publishes_nothing(client, auth_headers, recorder):
    resp = await client.post(
        RIDES,
        headers=auth_headers,
        json={"pickup_lat": 999, "pickup_lng": 0, "dropoff_lat": 0, "dropoff_lng": 0},
    )
    assert resp.status_code == 422
    assert recorder.published == []


async def test_request_succeeds_without_kafka(client, auth_headers):
    # No get_kafka override here -> the real (unstarted) singleton is used, which
    # no-ops on publish. The request must still succeed.
    resp = await client.post(RIDES, headers=auth_headers, json=_RIDE_BODY)
    assert resp.status_code == 201
