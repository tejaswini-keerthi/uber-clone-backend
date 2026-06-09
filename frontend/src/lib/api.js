// Thin fetch wrapper around the backend API.
//
// - Attaches the bearer access token for authenticated calls.
// - On a 401 it transparently rotates the refresh token once (matching the
//   backend's /auth/refresh rotation) and retries the original request.
// - Throws an ApiError carrying the backend's `detail` message and status.
import { API_BASE_URL, API_PREFIX } from "./config";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "./tokens";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function url(path) {
  return `${API_BASE_URL}${API_PREFIX}${path}`;
}

async function parse(response) {
  let body = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const detail =
      (body && body.detail) || response.statusText || "Request failed";
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }
  return body;
}

async function tryRefresh() {
  const refresh_token = getRefreshToken();
  if (!refresh_token) return false;
  const resp = await fetch(url("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!resp.ok) {
    clearTokens();
    return false;
  }
  setTokens(await resp.json());
  return true;
}

export async function apiFetch(
  path,
  { method = "GET", body, auth = true, _retried = false } = {},
) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(url(path), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401 && auth && !_retried) {
    if (await tryRefresh()) {
      return apiFetch(path, { method, body, auth, _retried: true });
    }
  }
  return parse(response);
}

// --- Endpoint helpers --------------------------------------------------------
export const AuthAPI = {
  register: (data) => apiFetch("/auth/register", { method: "POST", body: data, auth: false }),
  login: (email, password) =>
    apiFetch("/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => apiFetch("/auth/me"),
  logout: (refresh_token) =>
    apiFetch("/auth/logout", { method: "POST", body: { refresh_token } }),
};

export const RidesAPI = {
  request: (data) => apiFetch("/rides", { method: "POST", body: data }),
  list: () => apiFetch("/rides"),
  get: (id) => apiFetch(`/rides/${id}`),
  match: (id) => apiFetch(`/rides/${id}/match`, { method: "POST" }),
  start: (id) => apiFetch(`/rides/${id}/start`, { method: "POST" }),
  complete: (id) => apiFetch(`/rides/${id}/complete`, { method: "POST" }),
  cancel: (id, reason) =>
    apiFetch(`/rides/${id}/cancel`, { method: "POST", body: { reason: reason || null } }),
};

export const DriversAPI = {
  create: (data) => apiFetch("/drivers", { method: "POST", body: data }),
  me: () => apiFetch("/drivers/me"),
  get: (id) => apiFetch(`/drivers/${id}`),
  setStatus: (status) =>
    apiFetch("/drivers/me/status", { method: "PATCH", body: { status } }),
  setLocation: (lat, lng) =>
    apiFetch("/drivers/me/location", { method: "POST", body: { lat, lng } }),
};
