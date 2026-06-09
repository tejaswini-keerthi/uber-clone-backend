"""Ride lifecycle business logic — the state machine lives here.

Allowed transitions:
    requested  -> matched | cancelled
    matched    -> on_trip | cancelled
    on_trip    -> completed | cancelled
    completed  -> (terminal)
    cancelled  -> (terminal)

Driver matching (step 6), Kafka publish (step 8), WebSocket broadcasts (step 7)
and surge pricing (step 9) plug into these methods in later steps. The driver's
own status is kept in sync: it becomes `on_trip` (busy) when matched and returns
to `online` when the ride completes or is cancelled.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    NoAvailableDriverError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.geo import encode_geohash, geohash_neighbors, haversine_km
from app.core.kafka import KafkaPublisher
from app.core.redis import RedisCache
from app.core.websocket_manager import manager
from app.models.driver import Driver, DriverStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.repositories.driver_repository import DriverRepository
from app.repositories.ride_repository import RideRepository
from app.schemas.ride import RideRead, RideRequest, RideRequestEvent
from app.services.pricing_service import PricingService

_ALLOWED_TRANSITIONS: dict[RideStatus, set[RideStatus]] = {
    RideStatus.requested: {RideStatus.matched, RideStatus.cancelled},
    RideStatus.matched: {RideStatus.on_trip, RideStatus.cancelled},
    # Once a trip is underway it can only complete — cancellation is no longer
    # allowed (the rider is already in the car).
    RideStatus.on_trip: {RideStatus.completed},
    RideStatus.completed: set(),
    RideStatus.cancelled: set(),
}


class RideService:
    def __init__(
        self,
        db: AsyncSession,
        redis: RedisCache | None = None,
        kafka: KafkaPublisher | None = None,
        pricing: PricingService | None = None,
    ) -> None:
        self.db = db
        self.redis = redis
        self.kafka = kafka
        self.pricing = pricing
        self.rides = RideRepository(db)
        self.drivers = DriverRepository(db)

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _ensure_transition(self, ride: Ride, target: RideStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[ride.status]:
            raise ConflictError(
                f"Cannot move ride from '{ride.status.value}' to '{target.value}'"
            )

    async def _broadcast(self, ride: Ride) -> None:
        """Fan out the current ride state to the ride's WebSocket room. The
        payload carries the in-memory snapshot, so subscribers get accurate data
        even though the request transaction hasn't committed yet."""
        payload = {
            "type": "ride_update",
            "event": ride.status.value,
            "ride": RideRead.model_validate(ride).model_dump(mode="json"),
        }
        await manager.broadcast(str(ride.id), payload)

    def _compute_fare(self, distance_km: float, surge_multiplier: float) -> float:
        if self.pricing is not None:
            return self.pricing.compute_fare(distance_km, surge_multiplier)
        # Fallback to the same formula when no pricing service is wired in.
        return round(
            (settings.base_fare + distance_km * settings.per_km_rate) * surge_multiplier, 2
        )

    # --- creation ------------------------------------------------------------
    async def request_ride(self, rider: User, data: RideRequest) -> Ride:
        # A rider may not start a new ride while one is already active.
        if await self.rides.get_active_ride_for_rider(rider.id) is not None:
            raise ConflictError("You already have an active ride in progress")

        distance_km = round(
            haversine_km(
                data.pickup_lat, data.pickup_lng, data.dropoff_lat, data.dropoff_lng
            ),
            3,
        )
        pickup_geohash = encode_geohash(data.pickup_lat, data.pickup_lng)

        # Surge multiplier via cache-aside on the surge pricing engine (1.0 if
        # no pricing service is configured or the API is unavailable).
        surge_multiplier = 1.0
        if self.pricing is not None:
            surge_multiplier = await self.pricing.get_surge_multiplier(pickup_geohash)

        ride = await self.rides.create(
            rider_id=rider.id,
            pickup_lat=data.pickup_lat,
            pickup_lng=data.pickup_lng,
            pickup_geohash=pickup_geohash,
            dropoff_lat=data.dropoff_lat,
            dropoff_lng=data.dropoff_lng,
            city=data.city or settings.default_city,
            distance_km=distance_km,
            surge_multiplier=surge_multiplier,
            estimated_fare=self._compute_fare(distance_km, surge_multiplier),
        )

        # Commit BEFORE publishing so we never emit a ride-request event for a
        # ride that didn't persist (publish-after-commit ordering). Publishing is
        # best-effort and never fails the request.
        await self.db.commit()
        if self.kafka is not None:
            event = RideRequestEvent.from_ride(ride).model_dump(mode="json")
            await self.kafka.publish_ride_request(event)
        return ride

    # --- reads ---------------------------------------------------------------
    async def _get_or_404(self, ride_id: uuid.UUID) -> Ride:
        ride = await self.rides.get_by_id(ride_id)
        if ride is None:
            raise NotFoundError("Ride not found")
        return ride

    async def _assert_can_view(self, ride: Ride, user: User) -> None:
        if ride.rider_id == user.id:
            return
        if ride.driver_id is not None:
            driver = await self.drivers.get_by_id(ride.driver_id)
            if driver is not None and driver.user_id == user.id:
                return
        raise PermissionDeniedError("You are not a participant in this ride")

    async def get_ride(self, ride_id: uuid.UUID, user: User) -> Ride:
        ride = await self._get_or_404(ride_id)
        await self._assert_can_view(ride, user)
        return ride

    async def list_my_rides(self, user: User) -> list[Ride]:
        driver = await self.drivers.get_by_user_id(user.id)
        if driver is not None:
            return await self.rides.list_for_driver(driver.id)
        return await self.rides.list_for_rider(user.id)

    # --- matching ------------------------------------------------------------
    async def match_ride(self, ride_id: uuid.UUID, user: User) -> Ride:
        """Match a requested ride to the nearest available driver (PostGIS).

        Geohash pre-filter (pickup cell + 8 neighbours) narrows candidates; the
        spatial query ranks by true distance. Falls back to an unconstrained
        radius search if the zone pre-filter finds nobody, so a driver just
        outside the neighbour cells but within radius is still reachable.
        """
        ride = await self._get_or_404(ride_id)
        if ride.rider_id != user.id:
            raise PermissionDeniedError("Only the rider can request matching")
        if ride.status != RideStatus.requested:
            raise ConflictError("Ride is not awaiting a match")

        zones = [ride.pickup_geohash, *geohash_neighbors(ride.pickup_geohash)]
        radius = settings.driver_search_radius_meters
        driver = await self.drivers.find_nearest_available_driver(
            lat=ride.pickup_lat, lng=ride.pickup_lng, radius_m=radius, zones=zones
        )
        if driver is None:  # fallback: drop the zone pre-filter
            driver = await self.drivers.find_nearest_available_driver(
                lat=ride.pickup_lat, lng=ride.pickup_lng, radius_m=radius, zones=None
            )
        if driver is None:
            raise NoAvailableDriverError()

        return await self.assign_driver(ride, driver)

    # --- transitions ---------------------------------------------------------
    async def assign_driver(self, ride: Ride, driver: Driver) -> Ride:
        """requested -> matched. Reserves the driver (status -> on_trip)."""
        self._ensure_transition(ride, RideStatus.matched)
        if driver.status != DriverStatus.online:
            raise ConflictError("Driver is not available")
        ride.driver_id = driver.id
        ride.status = RideStatus.matched
        ride.matched_at = self._now()
        await self.drivers.set_status(driver, DriverStatus.on_trip)  # reserve driver
        if self.redis is not None:  # remove from the available-drivers snapshot
            await self.redis.mark_unavailable(driver.id, driver.geohash_zone)
        await self.rides.flush()
        await self._broadcast(ride)
        return ride

    async def _require_assigned_driver(self, ride: Ride, user: User) -> Driver:
        if ride.driver_id is None:
            raise ConflictError("Ride has no assigned driver")
        driver = await self.drivers.get_by_id(ride.driver_id)
        if driver is None or driver.user_id != user.id:
            raise PermissionDeniedError("Only the assigned driver can do this")
        return driver

    async def start_trip(self, ride_id: uuid.UUID, user: User) -> Ride:
        ride = await self._get_or_404(ride_id)
        await self._require_assigned_driver(ride, user)
        self._ensure_transition(ride, RideStatus.on_trip)
        ride.status = RideStatus.on_trip
        ride.started_at = self._now()
        await self.rides.flush()
        await self._broadcast(ride)
        return ride

    async def complete_trip(self, ride_id: uuid.UUID, user: User) -> Ride:
        ride = await self._get_or_404(ride_id)
        driver = await self._require_assigned_driver(ride, user)
        self._ensure_transition(ride, RideStatus.completed)
        ride.status = RideStatus.completed
        ride.completed_at = self._now()
        ride.final_fare = ride.estimated_fare
        await self.drivers.set_status(driver, DriverStatus.online)  # free the driver
        if self.redis is not None and driver.geohash_zone:
            await self.redis.mark_available(driver.id, driver.geohash_zone)
        await self.rides.flush()
        await self._broadcast(ride)
        return ride

    async def cancel_ride(
        self, ride_id: uuid.UUID, user: User, reason: str | None = None
    ) -> Ride:
        ride = await self._get_or_404(ride_id)
        await self._assert_can_view(ride, user)  # rider or assigned driver
        self._ensure_transition(ride, RideStatus.cancelled)
        ride.status = RideStatus.cancelled
        ride.cancelled_at = self._now()
        ride.cancellation_reason = reason
        # Free a reserved driver, if any.
        if ride.driver_id is not None:
            driver = await self.drivers.get_by_id(ride.driver_id)
            if driver is not None and driver.status == DriverStatus.on_trip:
                await self.drivers.set_status(driver, DriverStatus.online)
                if self.redis is not None and driver.geohash_zone:
                    await self.redis.mark_available(driver.id, driver.geohash_zone)
        await self.rides.flush()
        await self._broadcast(ride)
        return ride
