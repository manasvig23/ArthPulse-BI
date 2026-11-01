import { useCallback, useEffect, useRef, useState } from "react";

// Change via a .env file (VITE_API_BASE) when the backend moves off localhost.
export const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

// ---------------------------------------------------------------- token
const TOKEN_KEY = "arthpulse_token";

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
};

export const setToken = token => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable: the user simply signs in again next visit */ }
};

/** Thrown when the server says the token is missing, expired or invalid. */
export class AuthError extends Error {}

async function request(path) {
  const token = getToken();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (response.status === 401) throw new AuthError("Your session has expired. Please sign in again.");
  if (response.status === 403) throw new Error("Your role cannot open this section.");
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

export const getJson = path => request(path);

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Sign-in failed");
  return body;
}

/** Signed-in POST / PATCH / DELETE. Throws an Error carrying the server's plain-English reason. */
export async function sendJson(method, path, payload) {
  const token = getToken();
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) throw new AuthError("Your session has expired. Please sign in again.");
  if (!response.ok) throw new Error(explain(body.detail) || `Request failed (${response.status})`);
  return body;
}

// FastAPI sends a string for our own errors and a list for malformed input
function explain(detail) {
  if (Array.isArray(detail)) return detail.map(d => d.msg).join("; ");
  return detail;
}

// ------------------------------------------------------------ dashboard
/**
 * Loads only what this user's role may see -- asking for anything else would
 * just come back 403. While a new period loads, the old data stays on screen.
 */
export function useDashboardData(period, areas, onAuthError) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const authErrorRef = useRef(onAuthError);
  authErrorRef.current = onAuthError;
  const areasKey = areas.join(",");

  useEffect(() => {
    let cancelled = false;
    const q = `?period=${period}`;
    const has = area => areasKey.split(",").includes(area);

    const plan = {
      sales: has("sales") && `/api/sales${q}`,
      purchases: has("purchases") && `/api/purchases${q}`,
      inventory: has("inventory") && "/api/inventory",
      payments: has("cashflow") && "/api/payments",
      alerts: has("alerts") && "/api/alerts",
      compliance: has("compliance") && "/api/compliance",
      summary: `/api/summary${q}`,
    };
    const keys = Object.keys(plan).filter(k => plan[k]);

    setLoading(true);
    setError(null);

    Promise.all(keys.map(k => getJson(plan[k])))
      .then(results => {
        if (cancelled) return;
        const next = { sales: [], purchases: [], inventory: [], payments: [], alerts: [], compliance: null, summary: null };
        keys.forEach((k, i) => { next[k] = results[i]; });
        setData(next);
        setLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        if (err instanceof AuthError) { authErrorRef.current?.(); return; }
        setError(err);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [period, areasKey, tick]);

  const reload = useCallback(() => setTick(t => t + 1), []);
  return { data, loading, error, reload };
}