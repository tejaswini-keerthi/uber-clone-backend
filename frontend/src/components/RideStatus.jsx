import { useEffect, useState } from "react";

import { DriversAPI, RidesAPI, ApiError } from "../lib/api";
import { useRideStatus } from "../hooks/useRideStatus";
import Map from "./Map";

const STEPS = ["requested", "matched", "on_trip", "completed"];

const LABELS = {
  requested: "Finding a driver",
  matched: "Driver on the way",
  on_trip: "On trip",
  completed: "Completed",
  cancelled: "Cancelled",
};

// Live ride status driven by the WebSocket. Also exposes rider actions
// (find driver / cancel) and shows the matched driver's details.
export default function RideStatus({ rideId, onReset }) {
  const { ride, status, connected } = useRideStatus(rideId);
  const [driver, setDriver] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (ride?.driver_id) {
      DriversAPI.get(ride.driver_id).then(setDriver).catch(() => setDriver(null));
    } else {
      setDriver(null);
    }
  }, [ride?.driver_id]);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  if (!ride) {
    return <p className="text-sm text-gray-500">Connecting to ride…</p>;
  }

  const terminal = status === "completed" || status === "cancelled";

  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <div className="h-[420px]">
        <Map
          pickup={{ lat: ride.pickup_lat, lng: ride.pickup_lng }}
          dropoff={{ lat: ride.dropoff_lat, lng: ride.dropoff_lng }}
          driver={driver?.current_lat ? { lat: driver.current_lat, lng: driver.current_lng } : null}
          onSelect={() => {}}
        />
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{LABELS[status] || status}</h2>
          <span
            className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-gray-300"}`}
            title={connected ? "Live" : "Reconnecting"}
          />
        </div>

        {status !== "cancelled" && (
          <ol className="space-y-2">
            {STEPS.map((step) => {
              const reached = STEPS.indexOf(step) <= STEPS.indexOf(status);
              return (
                <li key={step} className="flex items-center gap-2 text-sm">
                  <span
                    className={`inline-block h-4 w-4 rounded-full ${
                      reached ? "bg-black" : "bg-gray-200"
                    }`}
                  />
                  <span className={reached ? "font-medium" : "text-gray-400"}>
                    {LABELS[step]}
                  </span>
                </li>
              );
            })}
          </ol>
        )}

        <div className="rounded-lg bg-gray-50 p-3 text-sm">
          <Row label="Fare estimate" value={fare(ride.estimated_fare)} />
          {ride.final_fare != null && <Row label="Final fare" value={fare(ride.final_fare)} />}
          <Row label="Surge" value={`${ride.surge_multiplier}×`} />
          <Row label="Distance" value={ride.distance_km != null ? `${ride.distance_km} km` : "—"} />
        </div>

        {driver && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="font-medium">Your driver</p>
            <p className="text-gray-600">
              {driver.vehicle_color} {driver.vehicle_make} {driver.vehicle_model} ·{" "}
              {driver.vehicle_plate}
            </p>
            <p className="text-gray-600">Rating: {driver.rating}★</p>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="space-y-2">
          {status === "requested" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => RidesAPI.match(rideId))}
              className="w-full rounded-lg bg-black px-4 py-2.5 font-medium text-white disabled:opacity-40"
            >
              Find a driver
            </button>
          )}
          {(status === "requested" || status === "matched") && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => RidesAPI.cancel(rideId, "rider cancelled"))}
              className="w-full rounded-lg border px-4 py-2.5"
            >
              Cancel ride
            </button>
          )}
          {terminal && (
            <button
              type="button"
              onClick={onReset}
              className="w-full rounded-lg bg-black px-4 py-2.5 font-medium text-white"
            >
              Request another ride
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between py-0.5">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function fare(v) {
  return v != null ? `$${Number(v).toFixed(2)}` : "—";
}
