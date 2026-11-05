
import { useCallback, useEffect, useRef, useState } from "react";

// Change via a .env file (VITE_API_BASE) when the backend moves off localhost.
export const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

// ---------------------------------------------------------------- token

const TOKEN_KEY = "arthpulse_token";

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

export const setToken = token => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable: the user simply signs in again next visit.
  }
};

/** Thrown when the server says the token is missing, expired or invalid. */
export class AuthError extends Error {}

async function request(path) {
  const token = getToken();

  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (response.status === 401) {
    throw new AuthError("Your session has expired. Please sign in again.");
  }

  if (response.status === 403) {
    throw new Error("Your role cannot open this section.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${path} returned ${response.status}`);
  }

  return response.json();
}

export const getJson = path => request(path);

// ------------------------------------------------------------- downloads

export async function downloadBinary(path, filename) {
  const token = getToken();

  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (response.status === 401) {
    throw new AuthError("Your session has expired. Please sign in again.");
  }

  if (response.status === 403) {
    throw new Error("Your role cannot export this data.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Download failed (${response.status})`);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();

  URL.revokeObjectURL(url);
}

// --------------------------------------------------------------- login

export async function login(username, password) {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  const body = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(body.detail || "Sign-in failed");
  }

  return body;
}

/** Signed-in POST / PATCH / DELETE. */
export async function sendJson(method, path, payload) {
  const token = getToken();

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });

  const body = await response.json().catch(() => ({}));

  if (response.status === 401) {
    throw new AuthError("Your session has expired. Please sign in again.");
  }

  if (!response.ok) {
    throw new Error(explain(body.detail) || `Request failed (${response.status})`);
  }

  return body;
}

// FastAPI sends a string for our own errors and a list for malformed input.
function explain(detail) {
  if (Array.isArray(detail)) {
    return detail.map(item => item.msg).join("; ");
  }
  return detail;
}

// ---------------------------------------------------------- filter query

/**
 * Accepted filter properties:
 * period, start_date, end_date, financial_year,
 * product, customer, supplier, location, comparison.
 *
 * Empty values are omitted from the query string.
 */
export function buildDashboardQuery(filters = {}) {
  const params = new URLSearchParams();

  const allowed = [
    "period",
    "start_date",
    "end_date",
    "financial_year",
    "product",
    "customer",
    "supplier",
    "location",
    "comparison",
  ];

  allowed.forEach(key => {
    const value = filters[key];

    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });

  const query = params.toString();
  return query ? `?${query}` : "";
}

// ------------------------------------------------------------ dashboard

/**
 * Loads only what this user's role may see.
 *
 * The original three-argument call remains supported:
 * useDashboardData(period, areas, onAuthError)
 *
 * The fourth argument contains the active dashboard filters:
 * useDashboardData(period, areas, onAuthError, filters)
 */
export function useDashboardData(
  period,
  areas,
  onAuthError,
  filters = {},
) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  const authErrorRef = useRef(onAuthError);
  authErrorRef.current = onAuthError;

  const areasKey = (areas || []).join(",");
  const filterKey = JSON.stringify(filters || {});

  useEffect(() => {
    let cancelled = false;

    const activeFilters = {
      ...(filters || {}),
      period,
    };

    const query = buildDashboardQuery(activeFilters);
    const has = area => areasKey.split(",").includes(area);

    const plan = {
      sales: has("sales") && `/api/sales${query}`,
      purchases: has("purchases") && `/api/purchases${query}`,
      inventory: has("inventory")
        ? `/api/inventory${buildDashboardQuery({
            product: activeFilters.product,
            location: activeFilters.location,
          })}`
        : false,
      payments: has("cashflow") && "/api/payments",
      alerts: has("alerts") && "/api/alerts",
      compliance: has("compliance") && "/api/compliance",
      summary: `/api/summary${query}`,
      recommendations: "/api/recommendations",
      quality: "/api/quality",
      forecasts: "/api/forecasts",
      explainability: has("sales") && `/api/explainability?period=${encodeURIComponent(period)}`,
      sync: "/api/sync/status",
    };

    const keys = Object.keys(plan).filter(key => plan[key]);

    setLoading(true);
    setError(null);

    Promise.all(keys.map(key => getJson(plan[key])))
      .then(results => {
        if (cancelled) return;

        const next = {
          sales: [],
          purchases: [],
          inventory: [],
          payments: [],
          alerts: [],
          compliance: null,
          summary: null,
          recommendations: [],
          quality: null,
          forecasts: null,
          explainability: null,
          sync: null,
        };

        keys.forEach((key, index) => {
          next[key] = results[index];
        });

        setData(next);
        setLoading(false);
      })
      .catch(err => {
        if (cancelled) return;

        if (err instanceof AuthError) {
          authErrorRef.current?.();
          return;
        }

        setError(err);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [period, areasKey, filterKey, tick]);

  const reload = useCallback(() => {
    setTick(value => value + 1);
  }, []);

  return {
    data,
    loading,
    error,
    reload,
  };
}
