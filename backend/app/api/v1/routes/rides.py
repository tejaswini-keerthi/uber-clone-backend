"""Ride endpoints: request a ride, inspect, and drive the lifecycle.

Driver matching is wired into POST /rides in step 6; for now requesting a ride
leaves it in `requested`. The start/complete actions are driver-only and the
service enforces both the state machine and participant authorization.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, RideServiceDep
from app.schemas.ride import RideCancel, RideRead, RideRequest

router = APIRouter(prefix="/rides", tags=["rides"])


@router.post("", response_model=RideRead, status_code=status.HTTP_201_CREATED)
async def request_ride(
    data: RideRequest, current_user: CurrentUser, service: RideServiceDep
) -> RideRead:
    """Request a ride. Creates it in the `requested` state."""
    return await service.request_ride(current_user, data)


@router.get("", response_model=list[RideRead])
async def list_my_rides(
    current_user: CurrentUser, service: RideServiceDep
) -> list[RideRead]:
    """List the caller's rides (as rider, or as driver if they have a profile)."""
    return await service.list_my_rides(current_user)


@router.get("/{ride_id}", response_model=RideRead)
async def get_ride(
    ride_id: uuid.UUID, current_user: CurrentUser, service: RideServiceDep
) -> RideRead:
    return await service.get_ride(ride_id, current_user)


@router.post("/{ride_id}/match", response_model=RideRead)
async def match_ride(
    ride_id: uuid.UUID, current_user: CurrentUser, service: RideServiceDep
) -> RideRead:
    """Match a requested ride to the nearest available driver (PostGIS).

    In production this would be triggered by the worker consuming the Kafka
    `ride-requests` topic; exposing it here lets a rider trigger matching directly.
    """
    return await service.match_ride(ride_id, current_user)


@router.post("/{ride_id}/start", response_model=RideRead)
async def start_trip(
    ride_id: uuid.UUID, current_user: CurrentUser, service: RideServiceDep
) -> RideRead:
    """Assigned driver marks the trip started (matched -> on_trip)."""
    return await service.start_trip(ride_id, current_user)


@router.post("/{ride_id}/complete", response_model=RideRead)
async def complete_trip(
    ride_id: uuid.UUID, current_user: CurrentUser, service: RideServiceDep
) -> RideRead:
    """Assigned driver completes the trip (on_trip -> completed)."""
    return await service.complete_trip(ride_id, current_user)


@router.post("/{ride_id}/cancel", response_model=RideRead)
async def cancel_ride(
    ride_id: uuid.UUID,
    data: RideCancel,
    current_user: CurrentUser,
    service: RideServiceDep,
) -> RideRead:
    """Rider or assigned driver cancels the ride."""
    return await service.cancel_ride(ride_id, current_user, data.reason)
