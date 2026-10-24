// Thin client for the DecisionWatch backend. The UI never talks to the database.
const BASE = import.meta.env.VITE_API_URL ?? "/api";

const TOKEN_KEY = "dw_token";
export const auth = {
  get token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set token(value) {
    try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  },
};

// Where operational data lives. Either a customer-run agent inside their own network (the browser
// talks to it directly; address and token stay in this browser's storage) or the in-browser engine,
// which runs the whole backend inside this page so nothing is uploaded anywhere.
const AGENT_KEY = "dw_agent";
export const agent = {
  get connection() {
    try { return JSON.parse(localStorage.getItem(AGENT_KEY)); } catch { return null; }
  },
  connect(url, token) {
    try { localStorage.setItem(AGENT_KEY, JSON.stringify({ url: url.trim().replace(/\/+$/, ""), token: token.trim() })); } catch { /* storage unavailable */ }
  },
  useLocal() {
    try { localStorage.setItem(AGENT_KEY, JSON.stringify({ local: true })); } catch { /* storage unavailable */ }
  },
  disconnect() {
    try { localStorage.removeItem(AGENT_KEY); } catch { /* storage unavailable */ }
  },
};

// Accounts and billing live on the hosted site. Everything else is operational data, which a
// signed-in customer keeps on their own agent or in their browser (the shared demo is the only data hosted here).
const ACCOUNT_PATHS = ["/auth/", "/workspace/", "/integration-requests"];
const isAccountPath = (path) => ACCOUNT_PATHS.some((prefix) => path.startsWith(prefix));

function describe(status, statusText, data) {
  let detail = `${status} ${statusText ?? ""}`.trim();
  if (data && typeof data.detail === "string") detail = data.detail;
  else if (data && Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join("; ");
  else if (data && data.detail) detail = JSON.stringify(data.detail);
  return detail;
}

async function localRequest(method, path, params, body) {
  const { startEngine } = await import("./local/engine");
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  let engine;
  try {
    engine = await startEngine();
  } catch {
    throw new Error("The in-browser engine could not start. Reload the page, or connect an agent instead.");
  }
  const { status, body: data } = await engine.request(method, query.size ? `${path}?${query}` : path, body ? JSON.stringify(body) : null);
  if (status === 204) return null;
  if (status < 200 || status >= 300) throw new Error(describe(status, "", data));
  return data;
}

async function request(method, path, { params, body, connection } = {}) {
  const link = connection ?? (isAccountPath(path) ? null : agent.connection);
  if (link?.local) return localRequest(method, path, params, body);
  const url = new URL((link ? link.url : BASE) + path, window.location.origin);
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(link ? { Authorization: `Bearer ${link.token}` } : auth.token ? { Authorization: `Bearer ${auth.token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Could not reach the DecisionWatch API. Is the backend running?");
  }
  if (response.status === 204) return null;
  if (response.status === 401 && link && !connection) {
    agent.disconnect();
    window.location.assign("/agent");
    throw new Error("The agent rejected the token. Reconnect it.");
  }
  if (response.status === 401 && !link && auth.token && !path.startsWith("/auth/")) {
    // The session expired or was revoked: drop it and return to sign-in rather than failing every call.
    auth.token = null;
    window.location.assign("/login");
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!response.ok) {
    let data = null;
    try { data = await response.json(); } catch { /* keep the status text */ }
    throw new Error(describe(response.status, response.statusText, data));
  }
  return response.json();
}

export const api = {
  me: () => request("GET", "/auth/me"),
  probeAgent: (url, token) => request("GET", "/auth/me", { connection: { url: url.trim().replace(/\/+$/, ""), token: token.trim() } }),
  signup: (payload) => request("POST", "/auth/signup", { body: payload }),
  login: (payload) => request("POST", "/auth/login", { body: payload }),
  logout: () => request("POST", "/auth/logout"),
  syncStatus: () => request("GET", "/sync/status"),
  syncTest: () => request("POST", "/sync/test"),
  syncNow: () => request("POST", "/sync"),
  billing: () => request("GET", "/workspace/billing"),
  saveBilling: (payload) => request("PUT", "/workspace/billing", { body: payload }),
  importDatasets: () => request("GET", "/import/datasets"),
  importMapping: (dataset) => request("GET", `/import/${dataset}/mapping`),
  importRuns: () => request("GET", "/import/runs"),
  importPreview: (dataset, body) => request("POST", `/import/${dataset}/preview`, { body }),
  importCommit: (dataset, body) => request("POST", `/import/${dataset}/commit`, { body }),
  createIntegrationRequest: (payload) => request("POST", "/integration-requests", { body: payload }),
  brief: (asOf, limit, explain) => request("GET", "/brief", { params: { as_of: asOf, limit, explain } }),
  decision: (id, asOf) => request("GET", `/decisions/${encodeURIComponent(id)}`, { params: { as_of: asOf } }),
  suggest: (id, asOf) => request("POST", `/decisions/${encodeURIComponent(id)}/suggestion`, { params: { as_of: asOf } }),
  metrics: (asOf) => request("GET", "/metrics", { params: { as_of: asOf } }),
  staleness: (asOf, staleAfterDays) =>
    request("GET", "/staleness", { params: { as_of: asOf, stale_after_days: staleAfterDays } }),
  recheck: (asOf) => request("POST", "/events/recheck", { params: { as_of: asOf } }),
  act: (id, action, note) =>
    request("POST", `/decisions/${encodeURIComponent(id)}/action`, { body: { action, note } }),
  extract: (id) => request("POST", `/decisions/${encodeURIComponent(id)}/extract`),
  confirm: (id, payload) =>
    request("POST", `/decisions/${encodeURIComponent(id)}/assumptions/confirm`, { body: payload }),
};
