"""Ride ORM model + the lifecycle state enum.

Pickup and dropoff each carry a PostGIS geography(Point) (for spatial work) and
plain lat/lng floats (for cheap serialization) — same dual-representation
rationale as Driver. `pickup_geohash` is the zone key used for driver matching
(step 6) and the Kafka surge event (step 8).

Lifecycle timestamps (matched_at/started_at/completed_at/cancelled_at) are set
by RideService as the ride moves through its state machine.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geography
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RideStatus(str, enum.Enum):
    requested = "requested"  # rider asked; awaiting a driver
    matched = "matched"  # a driver is assigned, en route to pickup
    on_trip = "on_trip"  # rider on board, trip in progress
    completed = "completed"  # finished successfully (terminal)
    cancelled = "cancelled"  # cancelled by rider or driver (terminal)


class Ride(Base, TimestampMixin):
    __tablename__ = "rides"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"), index=True, nullable=True
    )

    status: Mapped[RideStatus] = mapped_column(
        SAEnum(RideStatus, name="ride_status"),
        default=RideStatus.requested,
        server_default=RideStatus.requested.value,
        nullable=False,
        index=True,
    )

    # Pickup
    pickup_lat: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_lng: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_geohash: Mapped[str] = mapped_column(String(12), index=True, nullable=False)
    pickup_location: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )

    # Dropoff
    dropoff_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dropoff_lng: Mapped[float] = mapped_column(Float, nullable=False)
    dropoff_location: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )

    city: Mapped[str] = mapped_column(String(128), nullable=False)

    # Pricing
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    surge_multiplier: Mapped[float] = mapped_column(
        Float, default=1.0, server_default=text("1.0"), nullable=False
    )
    estimated_fare: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_fare: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Lifecycle timestamps
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Ride {self.id} status={self.status} driver={self.driver_id}>"
