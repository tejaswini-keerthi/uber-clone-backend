import { useState } from "react";

import DriverView from "../components/DriverView";
import RideRequest from "../components/RideRequest";
import RideStatus from "../components/RideStatus";
import { useAuth } from "../context/AuthContext";

const ACTIVE_RIDE_KEY = "rh_active_ride";

export default function Home() {
  const { user, logout } = useAuth();
  // Persist the active ride id so a refresh keeps showing live status.
  const [activeRideId, setActiveRideId] = useState(
    () => localStorage.getItem(ACTIVE_RIDE_KEY) || null,
  );

  const setActive = (id) => {
    if (id) localStorage.setItem(ACTIVE_RIDE_KEY, id);
    else localStorage.removeItem(ACTIVE_RIDE_KEY);
    setActiveRideId(id);
  };

  return (
    <div className="min-h-full bg-white">
      <header className="flex items-center justify-between border-b px-6 py-4">
        <h1 className="text-xl font-bold">RideHail</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-600">
            {user?.full_name} · <span className="rounded bg-gray-100 px-2 py-0.5">{user?.role}</span>
          </span>
          <button type="button" onClick={logout} className="rounded border px-3 py-1.5">
            Log out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl p-6">
        {user?.role === "driver" ? (
          <DriverView />
        ) : activeRideId ? (
          <RideStatus rideId={activeRideId} onReset={() => setActive(null)} />
        ) : (
          <RideRequest onCreated={(ride) => setActive(ride.id)} />
        )}
      </main>
    </div>
  );
}
