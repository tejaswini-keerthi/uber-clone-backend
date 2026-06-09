"""Driver business logic: profile creation, availability toggle, location updates."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.geo import encode_geohash
from app.core.redis import RedisCache
from app.models.driver import Driver, DriverStatus
from app.models.user import User, UserRole
from app.repositories.driver_repository import DriverRepository
from app.schemas.driver import DriverCreate


class DriverService:
    def __init__(self, db: AsyncSession, redis: RedisCache | None = None) -> None:
        self.db = db
        self.redis = redis
        self.drivers = DriverRepository(db)

    async def create_profile(self, user: User, data: DriverCreate) -> Driver:
        if user.role != UserRole.driver:
            raise PermissionDeniedError("Only users with the driver role can create a driver profile")
        if await self.drivers.get_by_user_id(user.id) is not None:
            raise ConflictError("Driver profile already exists for this user")
        return await self.drivers.create(
            user_id=user.id,
            vehicle_make=data.vehicle_make,
            vehicle_model=data.vehicle_model,
            vehicle_plate=data.vehicle_plate,
            vehicle_color=data.vehicle_color,
        )

    async def get_my_profile(self, user: User) -> Driver:
        driver = await self.drivers.get_by_user_id(user.id)
        if driver is None:
            raise NotFoundError("No driver profile for this user")
        return driver

    async def get_by_id(self, driver_id: uuid.UUID) -> Driver:
        driver = await self.drivers.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError("Driver not found")
        return driver

    async def set_status(self, user: User, status: DriverStatus) -> Driver:
        # on_trip is owned by the ride lifecycle, never set by the driver.
        if status not in (DriverStatus.online, DriverStatus.offline):
            raise ConflictError("Drivers may only set status to online or offline")
        driver = await self.get_my_profile(user)
        if driver.status == DriverStatus.on_trip:
            raise ConflictError("Cannot change availability while on a trip")
        # Going online without a known location would make the driver unmatchable.
        if status == DriverStatus.online and driver.current_lat is None:
            raise ConflictError("Set your location before going online")
        driver = await self.drivers.set_status(driver, status)

        # Keep the Redis "available drivers per zone" snapshot in sync.
        if self.redis is not None and driver.geohash_zone:
            if status == DriverStatus.online:
                await self.redis.mark_available(driver.id, driver.geohash_zone)
            else:
                await self.redis.mark_unavailable(driver.id, driver.geohash_zone)
        return driver

    async def update_location(self, user: User, lat: float, lng: float) -> Driver:
        driver = await self.get_my_profile(user)
        old_zone = driver.geohash_zone
        new_zone = encode_geohash(lat, lng)
        driver = await self.drivers.set_location(
            driver,
            lat=lat,
            lng=lng,
            geohash_zone=new_zone,
            updated_at=datetime.now(timezone.utc),
        )
        if self.redis is not None:
            await self.redis.upsert_location(driver.id, lat, lng, new_zone)
            # If an online driver crossed a zone boundary, move it between sets.
            if driver.status == DriverStatus.online:
                if old_zone and old_zone != new_zone:
                    await self.redis.mark_unavailable(driver.id, old_zone)
                await self.redis.mark_available(driver.id, new_zone)
        return driver
