import { useCallback, useState } from "react";

import { WS_BASE_URL } from "../lib/config";
import { getAccessToken } from "../lib/tokens";
import { useWebSocket } from "./useWebSocket";

// Subscribes to /ws/{rideId} and tracks the live ride state.
//
// The backend sends a `snapshot` on connect and a `ride_update` on every
// lifecycle transition; both carry the full ride object under `.ride`.
// Returns { ride, status, connected, events }.
export function useRideStatus(rideId) {
  const [ride, setRide] = useState(null);
  const [events, setEvents] = useState([]);

  const handleMessage = useCallback((msg) => {
    if (!msg || !msg.ride) return;
    setRide(msg.ride);
    if (msg.type === "ride_update") {
      setEvents((prev) => [...prev, { event: msg.event, at: Date.now() }]);
    }
  }, []);

  const token = getAccessToken();
  const url =
    rideId && token ? `${WS_BASE_URL}/ws/${rideId}?token=${token}` : null;
  const { connected } = useWebSocket(url, handleMessage);

  return { ride, status: ride?.status ?? null, connected, events };
}
