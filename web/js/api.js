// Talks to the API, and looks after this device's anonymous key.
//
// Identity flow: the first time a key is needed, the app asks the server for one
// (POST /api/identity) and keeps it in localStorage. Every request that needs it
// sends "Authorization: Bearer <key>". If storage is blocked the key is kept in memory for the current visit instead.

import { API_BASE } from "./config.js";

const STORAGE_KEY = "promptdebt.key";
let memoryKey = null;
let pendingKey = null;

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function getKey() {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? memoryKey;
  } catch {
    return memoryKey;
  }
}

export function setKey(key) {
  memoryKey = key;
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: the in-memory copy is used.
  }
}

async function request(method, path, { body, key } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers.Authorization = `Bearer ${key}`;

  let response;
  try {
    response = await fetch(API_BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
  }

  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "error",
      error.message ?? "Something went wrong.",
    );
  }
  return data;
}

/** This device's key, creating one on the server the first time. */
export function ensureKey() {
  const existing = getKey();
  if (existing) return Promise.resolve(existing);
  pendingKey ??= request("POST", "/api/identity")
    .then(({ key }) => {
      setKey(key);
      return key;
    })
    .finally(() => {
      pendingKey = null;
    });
  return pendingKey;
}

/** A request that needs the key. If the server no longer knows it, get a new one once ONCE. */
async function authed(method, path, body) {
  try {
    return await request(method, path, { body, key: await ensureKey() });
  } catch (error) {
    if (error.code !== "invalid_key") throw error;
    setKey(null);
    return request(method, path, { body, key: await ensureKey() });
  }
}

export const api = {
  // Scans work without a key; sending one adds triage stuffies.
  scan: (url) => request("POST", "/api/scans", { body: { url }, key: getKey() }),
  getScan: (id) => request("GET", `/api/scans/${encodeURIComponent(id)}`, { key: getKey() }),
  // Runs the advisory AI review for a scan (or returns the saved one).
  reviewScan: (id) => request("POST", `/api/scans/${encodeURIComponent(id)}/review`),

  listWatchlist: () => authed("GET", "/api/watchlist"),
  getWatchItem: (id) => authed("GET", `/api/watchlist/${encodeURIComponent(id)}`),
  // Either { url, label } (scans the repo) or { scan_id }.
  addWatchItem: (entry) => authed("POST", "/api/watchlist", entry),
  updateWatchItem: (id, changes) =>
    authed("PATCH", `/api/watchlist/${encodeURIComponent(id)}`, changes),
  deleteWatchItem: (id) => authed("DELETE", `/api/watchlist/${encodeURIComponent(id)}`),
  rescanWatchItem: (id) => authed("POST", `/api/watchlist/${encodeURIComponent(id)}/rescan`),

  listTriage: () => authed("GET", "/api/triage"),
  createTriage: (entry) => authed("POST", "/api/triage", entry),
  updateTriage: (id, changes) => authed("PATCH", `/api/triage/${encodeURIComponent(id)}`, changes),
  deleteTriage: (id) => authed("DELETE", `/api/triage/${encodeURIComponent(id)}`),

  /** chec k key */
  checkKey: (key) => request("GET", "/api/identity/me", { key }),
  deleteIdentity: () => request("DELETE", "/api/identity", { key: getKey() }),
};
