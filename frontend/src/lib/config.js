// Central runtime config derived from Vite env vars.
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

export const API_PREFIX = "/api/v1";

export const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

// Derive the WebSocket origin from the API base (http->ws, https->wss).
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");
