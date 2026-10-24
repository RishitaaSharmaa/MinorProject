# DecisionWatch

DecisionWatch records why procurement decisions were made, turns those reasons into checkable conditions, and rechecks them when state changes arrive. It flags a decision only when a condition is invalid and the supplied estimated regret is strictly greater than the switching cost. Condition checks and flagging are deterministic; the LLM is only used for condition extraction and explanation.

## Quick demo (one command)

```powershell
docker compose up --build
```

Then open **http://localhost:8080**. The stack starts PostgreSQL, the API and the React console, loads the demo dataset and seeds a reviewed workflow on first start (`DEMO_MODE=true`, the default; set `DEMO_MODE=false` in `.env` to start empty). Restarts are idempotent; `docker compose down -v` resets everything. API docs: http://localhost:8000/docs. The "Get suggestion" panel needs `GROQ_API_KEY` in `.env`; everything else works without it.

## Run the application

Use Python 3.11 and Docker Compose. `.env.example` supplies local-only PostgreSQL credentials; copy it to `.env` to customize settings or provide `GROQ_API_KEY`. Start the backend and database with:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Alembic migrations run automatically when the app container starts. The API docs are at `http://localhost:8000/docs`. Load the generated dataset into the running database with:

```powershell
docker compose exec app python -m scripts.load_dataset
```

Loading the dataset never writes operational `Assumption` rows by itself -- those only come from a planner extracting and confirming proposals, so the app never silently trusts the generator's hidden answer key, and `/brief` stays empty until someone reviews at least one decision. To see the full review workflow (confirmed assumptions, detected violations, a populated morning brief) immediately, bulk-confirm the deterministic, ERP-grounded structured proposals for every override decision instead of doing it one at a time:

```powershell
docker compose exec app python -m scripts.seed_review_workflow --as-of 2025-09-30
```

`POST /decisions/{id}/suggestion?as_of=YYYY-MM-DD` asks the LLM what to do about a decision whose assumption has broken (keep, reduce, delay or cancel), with a rationale, risks and next steps, and says whether it agrees with the deterministic recommendation. It is advisory only: it never changes flagging or ranking, its action is restricted to those four values, and it is refused (503) if it cites any figure not in the decision's own cost breakdown. It requires `GROQ_API_KEY`; it returns 409 for a decision with no broken assumption. The console shows it as a "Get suggestion" panel on each brief card and on Decision Detail.

Rerunning it is safe -- it reseeds cleanly rather than duplicating rows. `POST /decisions/{id}/extract` returns and persists structured/free-text assumption proposals. Review them with `POST /decisions/{id}/assumptions/confirm`, sending edited conditions under `accepted` and proposal IDs under `rejected_proposal_ids`; original and final values plus `accepted`/`edited`/`rejected` dispositions are retained for correction metrics. Confirming a proposal does not, by itself, mark it violated -- only a recheck pass does that:

```
POST /events/recheck?as_of=YYYY-MM-DD
```

replays every recorded state event up to that date and resets every non-retired assumption's status to match a deterministic point-in-time snapshot (safe to call repeatedly, and at any date, in any order). `GET /brief`, `GET /decisions/{id}`, and `GET /metrics` all read whatever `Assumption.status` the last recheck left behind, so call `/events/recheck` for a given `as_of` before reading any of them for that same date -- the React console in `ui/` (below) does this automatically whenever its date slider moves. Run the extraction baseline with `docker compose exec app python -m scripts.eval_extraction`. It reports per-condition precision, recall, and F1 against the isolated GT tables. Optional hand-authored examples belong in `data_generator/gold_set/*.jsonl` as `{"decision": {"id": "...", "free_text_reason": "...", "item_id": "...", "supplier_id": "..."}, "conditions": [{"type": "stock_lt", "entity_ref": "item:SKU1", "op": "<", "value": 10}]}`.

## Live events and MCP

**Event ingest.** External systems push changes instead of waiting for a CSV load. Set `INGEST_API_KEY` (the local-only default in `.env.example` is `dev-ingest-key`; ingest returns 503 while it is empty):

```powershell
curl -X POST http://localhost:8000/events -H "X-API-Key: dev-ingest-key" -H "Content-Type: application/json" `
  -d '{"id":"erp-90210","entity_type":"item","entity_id":"SKU001","field":"stock_qty","new_value":4}'
```

`POST /events/batch` takes up to 1000. Events are idempotent on `id` (a retry returns `duplicate: true`), and only the assumptions watching that entity/field are rechecked; the response lists the decisions just invalidated. A late-arriving event older than one already stored for the same entity/field triggers a full replay instead (`full_recheck: true`). Set `ALERT_WEBHOOK_URL` to POST a JSON summary (Slack/Teams-compatible `text` field) when an event breaks assumptions. `entity_type` is `item` or `supplier`; `field` matches the assumption conditions (e.g. `stock_qty`, `lead_time_days`, `strike_status`).

**MCP server.** `mcp_server/` exposes the API to AI agents (Claude Desktop/Code, etc.) over stdio. It is a separate process that only calls the REST API:

```powershell
python -m pip install -e ".[mcp]"
$env:DECISIONWATCH_API_URL = "http://localhost:8000"; $env:INGEST_API_KEY = "dev-ingest-key"
python -m mcp_server.server          # add --http for streamable HTTP
```

Tools: `get_morning_brief`, `get_decision`, `suggest_action`, `ingest_event`, `get_metrics`. `record_action` (which writes a decision outcome) is registered only when `DECISIONWATCH_MCP_ALLOW_WRITES=true`. Client config example: `{"command": "python", "args": ["-m", "mcp_server.server"], "env": {"DECISIONWATCH_API_URL": "http://localhost:8000", "INGEST_API_KEY": "dev-ingest-key"}}`.

## Self-serve workspaces and ERP integration (free 1-month trial)

Customers connect their own ERP data from the website; they never receive our code. The flow is **sign up -> export CSVs from any ERP -> upload and match columns in the browser -> preview -> import**, with `/integrate` documenting the steps and capturing sales leads (`POST /integration-requests`, listed with the `X-API-Key` at `GET /integration-requests`).

**Workspaces.** `POST /auth/signup` creates a tenant with a 30-day trial, an owner user and a bearer session (`/auth/login`, `/auth/logout`, `/auth/me`). Each tenant gets its **own database schema** (`t_<12 hex>`) holding a full copy of the operational tables; a request is bound to its tenant's schema with SQLAlchemy's `schema_translate_map` (`app/tenancy.py`), so services and queries are tenant-unaware and tenants cannot see each other's rows. The shared demo data stays in the default schema and is what unauthenticated visitors see. Control-plane tables (`tenants`, `users`, `auth_sessions`, `integration_requests`) live in the default schema (migrations `0007`, `0008`); tenant schemas are created from the models at sign-up.

Settings: `AUTH_REQUIRED` (default `false`: anonymous requests use the demo workspace; set `true` in production so every endpoint needs a session or a tenant key), `TRIAL_DAYS` (30), `SESSION_TTL_DAYS` (7). After a trial ends, a workspace becomes read-only (writes return 402, reads still work).

**Importing data.** `app/services/importer.py` defines five canonical datasets (`suppliers`, `items`, `purchase_orders`, `stock_levels`, `state_events`). `GET /import/datasets` describes them; `POST /import/{dataset}/preview` parses a CSV (delimiter auto-detected), suggests a column mapping from names/synonyms (SKU, Vendor Code, PO No, ...), validates every row (numbers like `1,20,000`, `16%`, several date formats, references to suppliers/items, duplicates) and writes nothing; `POST /import/{dataset}/commit` upserts the valid rows (or all rows, or only valid ones with `skip_invalid`), saves the mapping for next time and logs an import run. Re-uploading is idempotent. `stock_levels` and `state_events` also run the existing live-recheck, so assumptions break the moment the data says so. Import order: suppliers, items, purchase orders, stock.

**Real-time feed.** `POST /workspace/ingest-key` issues a per-workspace key (shown once, stored hashed) for `POST /events`; events land only in that workspace.

Limits and caveats: SQLite has no schemas, so the tenant tests attach one database file per tenant (development and tests only; production needs PostgreSQL). Future migrations to operational tables must also be applied to every tenant schema. Rate limiting is in-process, per instance.

## React console

`ui/` is a React (Vite) app. Its landing page explains what DecisionWatch is, the problem it solves and how it helps an enterprise; the console (`/console`) has four pages (Morning Brief, Confirm Assumptions, Decision Detail, Metrics) that talk only to the API, never the database. It is not part of the Docker image; run it separately once the API is up (requires Node.js 18+):

```powershell
cd ui
npm install
npm run dev
```

Open `http://localhost:5173`. In development, requests to `/api/*` are proxied to `http://localhost:8000`; set `VITE_PROXY_TARGET` to proxy elsewhere, or `VITE_API_URL` (see `ui/.env.example`) to build against an API on another origin, which then needs CORS enabled. The console's "Simulated date" slider drives every page and automatically calls `/events/recheck` for that date before rendering, so moving it forward and back in time replays the dataset's history live. `npm run build` writes a static bundle to `ui/dist/`.

For local development outside Docker, install with `python -m pip install -e ".[dev]"`, set `DATABASE_URL` to a local PostgreSQL URL, run `alembic upgrade head`, and start `uvicorn app.main:app --reload`. `python -m pytest` runs the tests. The `/app` code uses only operational models; answer-key tables are populated only by the loader and are never imported by the application package.

`ERP_CONNECTOR=synthetic` selects the PostgreSQL-backed connector the engine reads at runtime. Real ERPs are not read per request: the agent *syncs* them into its own database (see "Browser-only mode and ERP sync" below). The `sap_b1` entry of `ERP_CONNECTOR` is only a documented stub of per-call mappings. Evaluation code can pass `as_of` dates to the synthetic connector to replay history without reading later stock snapshots, forecasts, or supplier events.

`LLM_PROVIDER`/`LLM_MODEL` configure extraction and explanations; `NOTE_LLM_PROVIDER`/`NOTE_LLM_MODEL` configure synthetic note generation. Compose uses `DECISIONWATCH_LLM_MODEL` and `DECISIONWATCH_NOTE_LLM_MODEL`, defaulting to currently active Groq-hosted `openai/gpt-oss-20b` and `openai/gpt-oss-120b` models, because a local `.env` can retain older model IDs. Settings are loaded with pydantic-settings and reject using the same provider/model pair for extraction and synthetic notes. No API credentials are committed.

Run tests with `python -m pytest`.

## Synthetic procurement data

The generator creates six months of daily procurement and inventory data for a fictional mid-sized Indian SME. The simulation is seeded; buyer notes are generated with Groq by default and are nondeterministic.

## Run

Install dependencies, set `GROQ_API_KEY`, and run from the repository root:

```powershell
python -m pip install -r requirements.txt
$env:GROQ_API_KEY = "your-groq-api-key"
python -m data_generator.main
```

CSV files are written to `data_generator/output/`. All simulation and LLM settings live in `data_generator/config.py`. The default `NOTE_LLM_PROVIDER="groq"` uses Groq's SDK with `llama-3.3-70b-versatile` to make one batch request for override notes. Set `NOTE_LLM_MODEL` to choose another Groq model. For a complete offline run without API credentials, set `NOTE_LLM_PROVIDER` to `template`; this produces varied local notes. All structured labels and world data remain seeded in either mode.

## Tables

- `items`, `suppliers`: product and vendor master data. JSON price tiers are stored in one CSV cell.
- `sales_history`, `stock_snapshot`: daily units sold and end-of-day stock for each SKU.
- `weekly_forecasts`: forecast and realized demand for each item-week, including the injected signed forecast error.
- `decisions`: purchase-order decisions, structured MRP fields, override status, and optional buyer note. `structured_fields.true_assumptions` is present only for overrides.
- `assumptions`: one row per true override condition. The condition JSON includes its comparison operator, threshold, observed value, and entity scope. These rows are deterministic labels, not LLM extractions.
- `supplier_delivery_history`: promised and actual delivery dates for every generated PO. A positive `delay_days` is late.
- `state_events`: dated forecast, inventory, supplier-risk, lead-time, and price-tier changes.
- `ground_truth_violations`: an event/decision pair is included only when the event matches a prior assumption's entity and field and moves its observed value from satisfying to violating that condition. This is computed directly from the JSON conditions; no LLM is involved.
- `commitments`: cancellation economics and occasional linked commitments for supplier-consolidated orders.
- `outcomes`: simulated revisit result; `recommended_action` reflects the naive baseline.
- `baseline_event_flags`: the naive baseline flags every earlier decision touching an event's item or supplier, without checking the decision's specific assumptions.

`schema.sql` contains PostgreSQL-compatible table definitions for every CSV. The `output/` directory is created on first run.

## TODO Before Evaluation

- Fill `data_generator/gold_set/` with hand-authored or real-style examples, including notes and independently labeled assumptions.
- Do not use only the synthetic LLM-written notes as the final test set; they may reflect the note-generation model's phrasing and biases.
- Keep the extraction model/provider different from the note-generation model/provider. The extraction placeholder in `config.py` uses Groq `llama-3.1-8b-instant`; the generator rejects an identical provider/model pair if you change either configuration.
- Validate generated assumptions and violation labels against domain-reviewed examples before using them as production-quality ground truth.
## What the hosted site stores, and keeping your data in your own network (agent mode)

The hosted site stores **accounts only**: company name, user name and email, password hash, billing details (name, email, address, country, tax ID; never card numbers) and trial/plan state, plus the "Integrate your ERP" lead form. It holds no decisions, items, suppliers, events or free-text reasons. A signed-in account that asks the hosted API for operational data gets `403`; that data lives in the customer's own agent. The only data hosted here is the shared synthetic demo.

The agent is this same backend, run by the customer on their own server with their own database. Their browser talks to it directly, and imports, events and the console all go to the agent, not to the hosted site.

```powershell
$env:DB_PASSWORD = "<choose-a-password>"; $env:AGENT_TOKEN = "<long-random-secret>"
$env:DECISIONWATCH_SITE = "https://your-hosted-site"      # origin allowed to call the agent
docker compose -f docker-compose.agent.yml up -d --build
```

Sign up on the site, then it sends you to **/agent** to enter the agent's address and token (kept in that browser only). Every agent request needs the token; with `AGENT_TOKEN` unset the agent refuses all requests. Their ERP can push events to `POST <agent>/events` with the token as `X-API-Key`. Use `https` for an agent on another host (browsers block plain http except on localhost). `GROQ_API_KEY` is optional; without it extraction and suggestions are off, so no decision text leaves the network.

Upgrading from the earlier per-tenant-schema design: migration `0009` drops the schema pointers but deliberately leaves old `t_<hex>` schemas in place. List them with `\dn t_*` in psql and remove each with `DROP SCHEMA "t_..." CASCADE` once you have confirmed they are not needed.

## Browser-only mode and ERP sync

**Browser-only mode (no server, nothing uploaded).** After signing up, choose "Use this browser" on `/agent`. The whole backend (the same FastAPI app, importer, scoring and watcher) runs inside the page with Pyodide (Python compiled to WebAssembly) against a SQLite file that the page keeps in its own IndexedDB. Imports, rechecks, the brief and decisions all work; the first start downloads about 20 MB once, then it is cached. Limits: data is tied to one browser and device (clearing site data erases it), there is no live event push or ERP sync, and the LLM features are off because no key exists in the page. `LOCAL_MODE` skips authentication, so the backend refuses to start with it anywhere but a browser.

The engine files are built into the site by `npm run prepare:engine` (runs automatically before `dev` and `build`): the Pyodide runtime and packages come from the pinned Pyodide release, four pure-Python wheels are pinned and checked against PyPI's published hashes, and the backend source is bundled, so a user's browser fetches nothing from third parties. `npm run verify:engine` boots it in Node, imports data, reloads from the saved database and asserts no network request was made.

**ERP sync (agent).** Set `ERP_SOURCE=sap_b1` or `netsuite` plus credentials (see `.env.agent.example`; use a read-only ERP user). The agent reads suppliers, items, purchase orders and stock and loads them through the same validation and upserts as a CSV import, so synced and uploaded data behave identically. Stock goes through the event pipeline, and a changed supplier lead time or standing since the previous sync is recorded as a state event, so assumptions break and decisions are flagged. `POST /sync` (or the "Sync now" button on the Connect page) runs it on demand, `POST /sync/test` checks credentials, and `SYNC_INTERVAL_MINUTES` schedules it.

- **SAP Business One** (Service Layer): `BusinessPartners`, `Items`, `ItemGroups`, `PurchaseOrders` lines. SAP has no standard supplier lead-time or standing fields, so set `SAP_B1_LEAD_TIME_FIELD` / `SAP_B1_STRIKE_FIELD` to your own user-defined fields; otherwise `DEFAULT_LEAD_TIME_DAYS` applies and a frozen or invalid partner counts as a strike. Items with no main supplier are skipped and reported, not guessed.
- **NetSuite** (SuiteQL, token-based auth): each dataset is one query whose column aliases are the importer's field names. The defaults use standard records; override any with `NETSUITE_QUERY_<DATASET>` for custom fields or subsidiaries.

Verification status: both readers are tested against mocked ERP HTTP APIs (request shape, paging, signing, mapping, sync behaviour). They have not been run against a live SAP or NetSuite system, so expect to adjust field names or queries for a specific ERP version or customisation using a sandbox before relying on them.
