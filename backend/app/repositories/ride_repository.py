"""Data access for rides. SQLAlchemy only — no lifecycle rules."""
from __future__ import annotations

import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus


class RideRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, ride_id: uuid.UUID) -> Ride | None:
        return await self.db.get(Ride, ride_id)

    async def create(
        self,
        *,
        rider_id: uuid.UUID,
        pickup_lat: float,
        pickup_lng: float,
        pickup_geohash: str,
        dropoff_lat: float,
        dropoff_lng: float,
        city: str,
        distance_km: float,
        surge_multiplier: float,
        estimated_fare: float,
    ) -> Ride:
        ride = Ride(
            rider_id=rider_id,
            status=RideStatus.requested,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            pickup_geohash=pickup_geohash,
            pickup_location=WKTElement(f"POINT({pickup_lng} {pickup_lat})", srid=4326),
            dropoff_lat=dropoff_lat,
            dropoff_lng=dropoff_lng,
            dropoff_location=WKTElement(
                f"POINT({dropoff_lng} {dropoff_lat})", srid=4326
            ),
            city=city,
            distance_km=distance_km,
            surge_multiplier=surge_multiplier,
            estimated_fare=estimated_fare,
        )
        self.db.add(ride)
        await self.db.flush()
        await self.db.refresh(ride)
        return ride

    async def get_active_ride_for_rider(self, rider_id: uuid.UUID) -> Ride | None:
        """A rider's in-progress ride, if any. 'Active' means a driver is already
        committed to it (matched or on_trip) — multiple pending `requested` rides
        are allowed, but a rider can't open a new ride mid-trip."""
        result = await self.db.execute(
            select(Ride)
            .where(
                Ride.rider_id == rider_id,
                Ride.status.in_([RideStatus.matched, RideStatus.on_trip]),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_rider(self, rider_id: uuid.UUID) -> list[Ride]:
        result = await self.db.execute(
            select(Ride)
            .where(Ride.rider_id == rider_id)
            .order_by(Ride.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_driver(self, driver_id: uuid.UUID) -> list[Ride]:
        result = await self.db.execute(
            select(Ride)
            .where(Ride.driver_id == driver_id)
            .order_by(Ride.created_at.desc())
        )
        return list(result.scalars().all())

    async def flush(self) -> None:
        """Persist pending state-machine mutations within the request txn."""
        await self.db.flush()
