"""Pydantic v2 schemas for driver profiles, status, and location."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.driver import DriverStatus


class DriverCreate(BaseModel):
    vehicle_make: str = Field(min_length=1, max_length=64)
    vehicle_model: str = Field(min_length=1, max_length=64)
    vehicle_plate: str = Field(min_length=1, max_length=16)
    vehicle_color: str | None = Field(default=None, max_length=32)


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: DriverStatus
    vehicle_make: str
    vehicle_model: str
    vehicle_plate: str
    vehicle_color: str | None
    rating: float
    current_lat: float | None
    current_lng: float | None
    geohash_zone: str | None
    last_location_update: datetime | None


class DriverStatusUpdate(BaseModel):
    # Only online/offline are user-settable; on_trip is driven by the ride
    # lifecycle, never by the driver directly.
    status: DriverStatus = Field(
        description="Target availability status (online or offline)"
    )


class LocationUpdate(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
