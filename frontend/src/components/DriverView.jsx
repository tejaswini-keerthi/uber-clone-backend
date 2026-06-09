import { useCallback, useEffect, useState } from "react";

import { DriversAPI, RidesAPI, ApiError } from "../lib/api";

const ACTIVE = new Set(["matched", "on_trip"]);

// Driver dashboard: create profile, go online/offline, push location, and
// drive assigned rides through start/complete.
export default function DriverView() {
  const [profile, setProfile] = useState(null);
  const [rides, setRides] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadProfile = useCallback(async () => {
    try {
      setProfile(await DriversAPI.me());
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setProfile(null);
      else setError(e.message);
    }
  }, []);

  const loadRides = useCallback(async () => {
    try {
      setRides(await RidesAPI.list());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    (async () => {
      await loadProfile();
      await loadRides();
      setLoading(false);
    })();
  }, [loadProfile, loadRides]);

  const run = async (fn) => {
    setError(null);
    try {
      await fn();
      await loadProfile();
      await loadRides();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
    }
  };

  const pushLocation = () => {
    if (!navigator.geolocation) {
      // Fall back to a sample point if geolocation is unavailable.
      return run(() => DriversAPI.setLocation(37.7749, -122.4194));
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => run(() => DriversAPI.setLocation(pos.coords.latitude, pos.coords.longitude)),
      () => run(() => DriversAPI.setLocation(37.7749, -122.4194)),
    );
  };

  if (loading) return <p className="text-sm text-gray-500">Loading…</p>;
  if (!profile) return <CreateProfile onCreated={() => run(async () => {})} />;

  return (
    <div className="space-y-6">
      <section className="rounded-xl border p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">
              {profile.vehicle_make} {profile.vehicle_model}
            </h2>
            <p className="text-sm text-gray-600">
              Plate {profile.vehicle_plate} · Rating {profile.rating}★
            </p>
            <p className="text-sm text-gray-600">
              Status: <span className="font-medium">{profile.status}</span> ·
              {profile.current_lat
                ? ` ${profile.current_lat.toFixed(4)}, ${profile.current_lng.toFixed(4)}`
                : " location unknown"}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              profile.status === "online"
                ? "bg-green-100 text-green-700"
                : profile.status === "on_trip"
                  ? "bg-blue-100 text-blue-700"
                  : "bg-gray-100 text-gray-600"
            }`}
          >
            {profile.status}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={pushLocation} className="rounded border px-3 py-2 text-sm">
            Update my location
          </button>
          {profile.status !== "online" && profile.status !== "on_trip" && (
            <button
              type="button"
              onClick={() => run(() => DriversAPI.setStatus("online"))}
              className="rounded bg-green-600 px-3 py-2 text-sm text-white"
            >
              Go online
            </button>
          )}
          {profile.status === "online" && (
            <button
              type="button"
              onClick={() => run(() => DriversAPI.setStatus("offline"))}
              className="rounded bg-gray-800 px-3 py-2 text-sm text-white"
            >
              Go offline
            </button>
          )}
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold">Your rides</h3>
          <button type="button" onClick={loadRides} className="text-sm text-gray-500 underline">
            Refresh
          </button>
        </div>
        {rides.length === 0 && <p className="text-sm text-gray-500">No rides yet.</p>}
        <ul className="space-y-2">
          {rides.map((ride) => (
            <li key={ride.id} className="rounded-lg border p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{ride.status}</span>
                <span className="text-gray-500">
                  {ride.pickup_lat.toFixed(3)}, {ride.pickup_lng.toFixed(3)} →{" "}
                  {ride.dropoff_lat.toFixed(3)}, {ride.dropoff_lng.toFixed(3)}
                </span>
              </div>
              {ACTIVE.has(ride.status) && (
                <div className="mt-2 flex gap-2">
                  {ride.status === "matched" && (
                    <button
                      type="button"
                      onClick={() => run(() => RidesAPI.start(ride.id))}
                      className="rounded bg-black px-3 py-1.5 text-white"
                    >
                      Start trip
                    </button>
                  )}
                  {ride.status === "on_trip" && (
                    <button
                      type="button"
                      onClick={() => run(() => RidesAPI.complete(ride.id))}
                      className="rounded bg-black px-3 py-1.5 text-white"
                    >
                      Complete trip
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CreateProfile({ onCreated }) {
  const [form, setForm] = useState({
    vehicle_make: "",
    vehicle_model: "",
    vehicle_plate: "",
    vehicle_color: "",
  });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await DriversAPI.create(form);
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create profile");
    } finally {
      setSaving(false);
    }
  };

  const field = (name, label) => (
    <label className="block text-sm">
      <span className="text-gray-600">{label}</span>
      <input
        required={name !== "vehicle_color"}
        value={form[name]}
        onChange={(e) => setForm({ ...form, [name]: e.target.value })}
        className="mt-1 w-full rounded border px-3 py-2"
      />
    </label>
  );

  return (
    <form onSubmit={submit} className="max-w-md space-y-3 rounded-xl border p-4">
      <h2 className="text-lg font-semibold">Create your driver profile</h2>
      {field("vehicle_make", "Make")}
      {field("vehicle_model", "Model")}
      {field("vehicle_plate", "Plate")}
      {field("vehicle_color", "Color (optional)")}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-lg bg-black px-4 py-2.5 font-medium text-white disabled:opacity-40"
      >
        {saving ? "Saving…" : "Create profile"}
      </button>
    </form>
  );
}
