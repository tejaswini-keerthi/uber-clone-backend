import mapboxgl from "mapbox-gl";
import { useEffect, useRef } from "react";

import { MAPBOX_TOKEN } from "../lib/config";

const DEFAULT_CENTER = { lat: 37.7749, lng: -122.4194 }; // San Francisco

function makeMarker(color) {
  return new mapboxgl.Marker({ color });
}

// Interactive Mapbox map. Clicking the map calls onSelect({lat,lng}); pickup,
// dropoff and an optional driver position are rendered as colored markers.
// Falls back to a manual coordinate picker when no Mapbox token is configured.
export default function Map({ pickup, dropoff, driver, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markers = useRef({ pickup: null, dropoff: null, driver: null });
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!MAPBOX_TOKEN || mapRef.current || !containerRef.current) return undefined;
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [DEFAULT_CENTER.lng, DEFAULT_CENTER.lat],
      zoom: 12,
    });
    map.addControl(new mapboxgl.NavigationControl(), "top-right");
    map.on("click", (e) => {
      if (onSelectRef.current) {
        onSelectRef.current({ lat: e.lngLat.lat, lng: e.lngLat.lng });
      }
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Sync markers whenever the points change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const sync = (key, point, color) => {
      if (point) {
        if (!markers.current[key]) markers.current[key] = makeMarker(color);
        markers.current[key].setLngLat([point.lng, point.lat]).addTo(map);
      } else if (markers.current[key]) {
        markers.current[key].remove();
        markers.current[key] = null;
      }
    };
    sync("pickup", pickup, "#16a34a");
    sync("dropoff", dropoff, "#dc2626");
    sync("driver", driver, "#2563eb");
  }, [pickup, dropoff, driver]);

  if (!MAPBOX_TOKEN) {
    return <CoordinatePicker pickup={pickup} dropoff={dropoff} onSelect={onSelect} />;
  }

  return (
    <div
      ref={containerRef}
      className="h-full w-full rounded-xl overflow-hidden"
      style={{ minHeight: 320 }}
    />
  );
}

// Token-free fallback so the app is usable without a Mapbox account.
function CoordinatePicker({ pickup, dropoff, onSelect }) {
  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) =>
      onSelect({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
    );
  };
  return (
    <div className="h-full w-full rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4 text-sm">
      <p className="font-medium text-gray-700">Map preview</p>
      <p className="mt-1 text-gray-500">
        No Mapbox token configured. Use the buttons below to set points.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={useMyLocation}
          className="rounded bg-black px-3 py-1.5 text-white"
        >
          Use my location
        </button>
        <button
          type="button"
          onClick={() => onSelect({ lat: 37.7749, lng: -122.4194 })}
          className="rounded border px-3 py-1.5"
        >
          Sample SF point
        </button>
      </div>
      <dl className="mt-3 space-y-1 text-gray-600">
        <div>Pickup: {pickup ? `${pickup.lat.toFixed(4)}, ${pickup.lng.toFixed(4)}` : "—"}</div>
        <div>Dropoff: {dropoff ? `${dropoff.lat.toFixed(4)}, ${dropoff.lng.toFixed(4)}` : "—"}</div>
      </dl>
    </div>
  );
}
