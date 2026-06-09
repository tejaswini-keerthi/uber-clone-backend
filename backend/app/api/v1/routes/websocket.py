"""WebSocket endpoint for live ride status updates.

Clients connect to `/ws/{ride_id}?token=<access_token>`. The token is passed as
a query param because browsers can't set Authorization headers on the WebSocket
handshake. The connection is authenticated and authorized (rider or assigned
driver only) with a short-lived DB session that is released before the receive
loop starts — so a socket never ties up a DB connection.

Custom close codes:
  4401 unauthorized (missing/invalid token or unknown user)
  4403 forbidden (not a participant in this ride)
  4404 ride not found
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.api.deps import get_session_factory
from app.core.exceptions import AppError
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.core.websocket_manager import manager
from app.repositories.driver_repository import DriverRepository
from app.repositories.ride_repository import RideRepository
from app.repositories.user_repository import UserRepository
from app.schemas.ride import RideRead

router = APIRouter(tags=["websocket"])


async def _authorize(session_factory, ride_id: uuid.UUID, token: str | None):
    """Return (ride_snapshot) if the token's user may watch the ride, else raise
    an int close code. Uses a short-lived session and releases it on return."""
    if not token:
        return None, 4401
    try:
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except AppError:
        return None, 4401

    async with session_factory() as session:
        user = await UserRepository(session).get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            return None, 4401
        ride = await RideRepository(session).get_by_id(ride_id)
        if ride is None:
            return None, 4404
        # Participant check: rider, or the assigned driver's user.
        authorized = ride.rider_id == user.id
        if not authorized and ride.driver_id is not None:
            driver = await DriverRepository(session).get_by_id(ride.driver_id)
            authorized = driver is not None and driver.user_id == user.id
        if not authorized:
            return None, 4403
        snapshot = RideRead.model_validate(ride).model_dump(mode="json")
    return snapshot, None


@router.websocket("/ws/{ride_id}")
async def ride_updates(
    websocket: WebSocket,
    ride_id: uuid.UUID,
    token: str | None = Query(default=None),
    session_factory=Depends(get_session_factory),
) -> None:
    snapshot, close_code = await _authorize(session_factory, ride_id, token)
    if close_code is not None:
        await websocket.close(code=close_code)
        return

    room = str(ride_id)
    await manager.connect(room, websocket)
    # Send the current state immediately so a late subscriber isn't blind.
    await websocket.send_json({"type": "snapshot", "ride": snapshot})
    try:
        # We don't expect client messages; receiving just keeps the socket open
        # and lets us detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(room, websocket)
