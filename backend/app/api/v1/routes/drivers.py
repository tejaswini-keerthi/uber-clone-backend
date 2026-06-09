"""Driver endpoints: profile, availability toggle, location updates."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DriverServiceDep
from app.schemas.driver import (
    DriverCreate,
    DriverRead,
    DriverStatusUpdate,
    LocationUpdate,
)

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", response_model=DriverRead, status_code=status.HTTP_201_CREATED)
async def create_driver_profile(
    data: DriverCreate, current_user: CurrentUser, service: DriverServiceDep
) -> DriverRead:
    """Create the calling user's driver profile (requires the driver role)."""
    return await service.create_profile(current_user, data)


@router.get("/me", response_model=DriverRead)
async def get_my_driver_profile(
    current_user: CurrentUser, service: DriverServiceDep
) -> DriverRead:
    return await service.get_my_profile(current_user)


@router.patch("/me/status", response_model=DriverRead)
async def update_status(
    data: DriverStatusUpdate, current_user: CurrentUser, service: DriverServiceDep
) -> DriverRead:
    """Toggle availability (online/offline)."""
    return await service.set_status(current_user, data.status)


@router.post("/me/location", response_model=DriverRead)
async def update_location(
    data: LocationUpdate, current_user: CurrentUser, service: DriverServiceDep
) -> DriverRead:
    """Report the driver's current GPS position (updates geohash zone too)."""
    return await service.update_location(current_user, data.lat, data.lng)


@router.get("/{driver_id}", response_model=DriverRead)
async def get_driver(driver_id: uuid.UUID, service: DriverServiceDep) -> DriverRead:
    """Fetch a driver profile by id (e.g. a rider viewing their matched driver)."""
    return await service.get_by_id(driver_id)
