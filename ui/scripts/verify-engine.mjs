// End-to-end check of the browser-only tier, run in Node (same Pyodide runtime as the browser):
//   npm run prepare:engine && node scripts/verify-engine.mjs
// Boots the real backend in WebAssembly, imports data, reads the brief, then "reloads" from the saved
// database to prove persistence, and confirms no network request was made while it worked.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { createEngine } from "../src/local/core.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "engine");
const { loadPyodide } = await import(pathToFileURL(join(root, "pyodide", "pyodide.mjs")).href);

let stored = null;
const storage = { load: async () => stored, save: async (bytes) => { stored = new Uint8Array(bytes); } };
const options = {
  loadPyodide,
  indexURL: join(root, "pyodide") + "/",
  readJson: async (path) => JSON.parse(readFileSync(join(root, path), "utf8")),
  readBinary: async (path) => new Uint8Array(readFileSync(join(root, path))),
  storage,
  onStatus: (text) => text && console.log(" ", text),
};

const nativeFetch = globalThis.fetch;
let networkCalls = 0;
globalThis.fetch = (...args) => { networkCalls += 1; return nativeFetch(...args); };

const SUPPLIERS = "Vendor Code,Vendor Name,Lead Time\nV1,Acme Steel,10\nV2,Beta Bolts,20\n";
const ITEMS = "SKU,Description,Cost,Vendor,MOQ\nSKU1,Widget,12.5,V1,10\nSKU2,Gadget,100,V2,5\n";
const ORDERS = "PO No,SKU,Vendor,Qty,Price,Order Date,Reason\nPO1,SKU1,V1,100,12.5,2025-03-15,Supplier confirmed delivery by the 25th\n";
const json = (body) => JSON.stringify(body);

console.log("boot #1");
const engine = await createEngine(options);
const afterBoot = networkCalls;

let res = await engine.request("GET", "/auth/me");
assert.equal(res.status, 200);
assert.equal(res.body.agent, true);
assert.equal(res.body.demo, false);

for (const [dataset, csv_text, extra] of [["suppliers", SUPPLIERS, {}], ["items", ITEMS, {}], ["purchase_orders", ORDERS, {}]]) {
  res = await engine.request("POST", `/import/${dataset}/commit`, json({ csv_text, ...extra }));
  assert.equal(res.status, 201, `${dataset}: ${json(res.body)}`);
  assert.equal(res.body.rows_rejected, 0);
}

res = await engine.request("POST", "/events", json({ id: "e1", entity_type: "item", entity_id: "SKU1", field: "stock_qty", new_value: 3 }));
assert.equal(res.status, 401, "ingest endpoint must not be reachable without a key even in local mode");

res = await engine.request("POST", "/events/recheck?as_of=2025-06-01");
assert.equal(res.status, 200);
res = await engine.request("GET", "/brief?as_of=2025-06-01");
assert.equal(res.status, 200);
assert.ok(Array.isArray(res.body.cards));
res = await engine.request("GET", "/decisions/PO1?as_of=2025-06-01");
assert.equal(res.status, 200);
assert.equal(res.body.quantity, 100);
res = await engine.request("POST", "/auth/signup", json({ company_name: "X", name: "Y", email: "a@b.co", password: "long-enough-1" }));
assert.equal(res.status, 404, "accounts do not exist in the browser engine");
assert.ok(stored && stored.length > 0, "database was not persisted");

console.log("boot #2 (restored from the saved database)");
const reloaded = await createEngine(options);
res = await reloaded.request("GET", "/decisions/PO1");
assert.equal(res.status, 200, "data did not survive a reload");
res = await reloaded.request("GET", "/import/runs");
assert.equal(res.body.length, 3);

assert.equal(networkCalls, afterBoot, "the engine made network requests while handling data");
console.log(`ok: ${stored.length} bytes persisted, 0 network requests while handling data`);
process.exit(0);
