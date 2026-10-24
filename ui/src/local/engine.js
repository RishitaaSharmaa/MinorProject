// Browser wiring for the in-browser engine: where its files live and where the database is kept.
import { createEngine } from "./core";

const DB_NAME = "decisionwatch-local";
const STORE = "db";
const KEY = "sqlite";

function openDb() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB_NAME, 1);
    open.onupgradeneeded = () => open.result.createObjectStore(STORE);
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function withStore(mode, run) {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const request = run(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

// The database never leaves this browser. If storage is blocked the engine still works for the session.
const storage = {
  async load() {
    try { return (await withStore("readonly", (s) => s.get(KEY))) ?? null; } catch { return null; }
  },
  async save(bytes) {
    try { await withStore("readwrite", (s) => s.put(bytes, KEY)); } catch { /* storage unavailable */ }
  },
};

export async function clearLocalData() {
  try { await withStore("readwrite", (s) => s.delete(KEY)); } catch { /* nothing stored */ }
}

let status = "";
const listeners = new Set();
const setStatus = (value) => { status = value; listeners.forEach((fn) => fn(value)); };
export const engineStatus = {
  get: () => status,
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

let starting = null;
export function startEngine() {
  starting ??= (async () => {
    const base = `${import.meta.env.BASE_URL}engine/`;
    const url = (path) => new URL(base + path, window.location.origin).href;
    const { loadPyodide } = await import(/* @vite-ignore */ url("pyodide/pyodide.mjs"));
    return createEngine({
      loadPyodide,
      indexURL: url("pyodide/"),
      readJson: async (path) => (await fetch(url(path))).json(),
      readBinary: async (path) => new Uint8Array(await (await fetch(url(path))).arrayBuffer()),
      storage,
      onStatus: setStatus,
    });
  })().catch((error) => {
    starting = null;
    setStatus("");
    throw error;
  });
  return starting;
}
