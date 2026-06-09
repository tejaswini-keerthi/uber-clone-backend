"""Driver ORM model.

One-to-one with User (a user with role=driver gets exactly one driver profile).
Location is stored two ways on purpose:
  - `location`: a PostGIS geography(Point) used for the spatial ST_DWithin
    matching query (GiST-indexed) in step 6.
  - `current_lat` / `current_lng`: plain floats for cheap serialization in API
    responses without round-tripping through ST_X/ST_Y.
Both are always written together in DriverService.update_location, so they can't
drift. `geohash_zone` is the coarse pre-filter key derived from the same coords.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DriverStatus(str, enum.Enum):
    offline = "offline"  # not accepting rides
    online = "online"  # available for matching
    on_trip = "on_trip"  # currently serving a ride


class Driver(Base, TimestampMixin):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    # Vehicle
    vehicle_make: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(String(16), nullable=False)
    vehicle_color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[DriverStatus] = mapped_column(
        SAEnum(DriverStatus, name="driver_status"),
        default=DriverStatus.offline,
        server_default=DriverStatus.offline.value,
        nullable=False,
        index=True,
    )
    rating: Mapped[float] = mapped_column(
        Float, default=5.0, server_default=text("5.0"), nullable=False
    )

    # Location (see module docstring for why both representations exist).
    location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    current_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geohash_zone: Mapped[str | None] = mapped_column(String(12), index=True, nullable=True)
    last_location_update: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="driver")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Driver {self.id} status={self.status} zone={self.geohash_zone}>"
