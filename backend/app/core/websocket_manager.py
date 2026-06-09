"""Room-based WebSocket connection manager for ride status fan-out.

Each ride is a "room" keyed by its ride_id; rider and driver clients subscribe to
`/ws/{ride_id}` and receive every lifecycle event for that ride. The service
layer calls `manager.broadcast(ride_id, event)` on each state change.

Designing for 1,000+ concurrent connections
--------------------------------------------
- Connections are held in plain in-memory dict[str, set[WebSocket]]. add/remove/
  membership are O(1); broadcast is O(connections-in-that-room), not O(all).
- asyncio is single-threaded and I/O-bound here, so one Uvicorn worker sustains
  thousands of mostly-idle sockets cheaply (each is a coroutine + a small buffer).
  Scale further with multiple Uvicorn workers.
- Critically, a WebSocket does NOT hold a database connection for its lifetime:
  the endpoint authenticates with a short-lived session and releases it before
  entering the receive loop. So 1,000 sockets ≠ 1,000 DB connections.
- Broadcast is fault-tolerant: a send that fails (client gone) is collected and
  pruned rather than aborting the fan-out to healthy peers.
- Horizontal scale-out across processes is a documented next step: replace the
  in-memory map with Redis Pub/Sub (publish events to a channel per ride, each
  worker relays to its local sockets). The manager interface stays the same.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("app.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, room: str, websocket: WebSocket) -> None:
        """Accept the socket and add it to the room."""
        await websocket.accept()
        async with self._lock:
            self._rooms[room].add(websocket)
        logger.debug("ws connect room=%s size=%d", room, self.room_size(room))

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        connections = self._rooms.get(room)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                self._rooms.pop(room, None)

    async def broadcast(self, room: str, message: dict) -> None:
        """Send `message` (JSON) to every socket in the room; prune dead ones."""
        connections = list(self._rooms.get(room, ()))
        if not connections:
            return
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:  # client vanished mid-send
                dead.append(ws)
        for ws in dead:
            self.disconnect(room, ws)

    def room_size(self, room: str) -> int:
        return len(self._rooms.get(room, ()))

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._rooms.values())


# Process-wide singleton shared by the WS endpoint and the service layer.
manager = ConnectionManager()
