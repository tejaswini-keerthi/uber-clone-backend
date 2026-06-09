"""Pydantic v2 schemas for rides."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.models.ride import Ride, RideStatus


class RideRequest(BaseModel):
    pickup_lat: float = Field(ge=-90.0, le=90.0)
    pickup_lng: float = Field(ge=-180.0, le=180.0)
    dropoff_lat: float = Field(ge=-90.0, le=90.0)
    dropoff_lng: float = Field(ge=-180.0, le=180.0)
    city: str | None = Field(default=None, max_length=128)


class RideCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class RideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rider_id: uuid.UUID
    driver_id: uuid.UUID | None
    status: RideStatus

    pickup_lat: float
    pickup_lng: float
    pickup_geohash: str
    dropoff_lat: float
    dropoff_lng: float
    city: str

    distance_km: float | None
    surge_multiplier: float
    estimated_fare: float | None
    final_fare: float | None

    matched_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime


class RideRequestEvent(BaseModel):
    """Kafka `ride-requests` event. Field set and types must match the surge
    pricing engine's consumer EXACTLY — do not add/remove/rename fields here
    without updating that contract. `model_dump(mode="json")` yields UUIDs as
    strings and `timestamp` as an ISO-8601 string.
    """

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    ride_id: uuid.UUID
    rider_id: uuid.UUID
    pickup_lat: float
    pickup_lng: float
    pickup_geohash: str
    dropoff_lat: float
    dropoff_lng: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    city: str

    @classmethod
    def from_ride(cls, ride: Ride) -> "RideRequestEvent":
        return cls(
            ride_id=ride.id,
            rider_id=ride.rider_id,
            pickup_lat=ride.pickup_lat,
            pickup_lng=ride.pickup_lng,
            pickup_geohash=ride.pickup_geohash,
            dropoff_lat=ride.dropoff_lat,
            dropoff_lng=ride.dropoff_lng,
            city=ride.city,
        )
