// Thin client for the DecisionWatch backend. The UI never talks to the database.
const BASE = import.meta.env.VITE_API_URL ?? "/api";

async function request(method, path, { params, body } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Could not reach the DecisionWatch API. Is the backend running?");
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (data.detail) detail = JSON.stringify(data.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  brief: (asOf, limit, explain) => request("GET", "/brief", { params: { as_of: asOf, limit, explain } }),
  decision: (id, asOf) => request("GET", `/decisions/${encodeURIComponent(id)}`, { params: { as_of: asOf } }),
  suggest: (id, asOf) => request("POST", `/decisions/${encodeURIComponent(id)}/suggestion`, { params: { as_of: asOf } }),
  metrics: (asOf) => request("GET", "/metrics", { params: { as_of: asOf } }),
  recheck: (asOf) => request("POST", "/events/recheck", { params: { as_of: asOf } }),
  act: (id, action, note) =>
    request("POST", `/decisions/${encodeURIComponent(id)}/action`, { body: { action, note } }),
  extract: (id) => request("POST", `/decisions/${encodeURIComponent(id)}/extract`),
  confirm: (id, payload) =>
    request("POST", `/decisions/${encodeURIComponent(id)}/assumptions/confirm`, { body: payload }),
};
