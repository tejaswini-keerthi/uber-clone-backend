import { useState } from "react";

import { RidesAPI, ApiError } from "../lib/api";
import Map from "./Map";

// Pickup/dropoff selection on the map + ride request. Calls onCreated(ride)
// with the created (status=requested) ride.
export default function RideRequest({ onCreated }) {
  const [mode, setMode] = useState("pickup");
  const [pickup, setPickup] = useState(null);
  const [dropoff, setDropoff] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSelect = (coords) => {
    if (mode === "pickup") {
      setPickup(coords);
      setMode("dropoff");
    } else {
      setDropoff(coords);
    }
  };

  const submit = async () => {
    if (!pickup || !dropoff) return;
    setSubmitting(true);
    setError(null);
    try {
      const ride = await RidesAPI.request({
        pickup_lat: pickup.lat,
        pickup_lng: pickup.lng,
        dropoff_lat: dropoff.lat,
        dropoff_lng: dropoff.lng,
      });
      onCreated(ride);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not request ride");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <div className="h-[420px]">
        <Map pickup={pickup} dropoff={dropoff} onSelect={handleSelect} />
      </div>

      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Request a ride</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("pickup")}
            className={`flex-1 rounded px-3 py-2 text-sm ${
              mode === "pickup" ? "bg-green-600 text-white" : "border"
            }`}
          >
            Set pickup
          </button>
          <button
            type="button"
            onClick={() => setMode("dropoff")}
            className={`flex-1 rounded px-3 py-2 text-sm ${
              mode === "dropoff" ? "bg-red-600 text-white" : "border"
            }`}
          >
            Set dropoff
          </button>
        </div>

        <Point label="Pickup" point={pickup} dot="bg-green-600" />
        <Point label="Dropoff" point={dropoff} dot="bg-red-600" />

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="button"
          disabled={!pickup || !dropoff || submitting}
          onClick={submit}
          className="w-full rounded-lg bg-black px-4 py-3 font-medium text-white disabled:opacity-40"
        >
          {submitting ? "Requesting…" : "Request ride"}
        </button>
        <p className="text-xs text-gray-500">
          Click the map to drop a point. Pickup first, then dropoff.
        </p>
      </div>
    </div>
  );
}

function Point({ label, point, dot }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`inline-block h-3 w-3 rounded-full ${dot}`} />
      <span className="font-medium">{label}:</span>
      <span className="text-gray-600">
        {point ? `${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}` : "not set"}
      </span>
    </div>
  );
}
