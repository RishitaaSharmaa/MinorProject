# DecisionWatch

DecisionWatch records why procurement decisions were made, turns those reasons into checkable conditions, and rechecks them when state changes arrive. It flags a decision only when a condition is invalid and the supplied estimated regret is strictly greater than the switching cost. Condition checks and flagging are deterministic; the LLM is only used for condition extraction and explanation.

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

## React console

`ui/` is a React (Vite) app. Its landing page explains what DecisionWatch is, the problem it solves and how it helps an enterprise; the console (`/console`) has four pages (Morning Brief, Confirm Assumptions, Decision Detail, Metrics) that talk only to the API, never the database. It is not part of the Docker image; run it separately once the API is up (requires Node.js 18+):

```powershell
cd ui
npm install
npm run dev
```

Open `http://localhost:5173`. In development, requests to `/api/*` are proxied to `http://localhost:8000`; set `VITE_PROXY_TARGET` to proxy elsewhere, or `VITE_API_URL` (see `ui/.env.example`) to build against an API on another origin, which then needs CORS enabled. The console's "Simulated date" slider drives every page and automatically calls `/events/recheck` for that date before rendering, so moving it forward and back in time replays the dataset's history live. `npm run build` writes a static bundle to `ui/dist/`.

For local development outside Docker, install with `python -m pip install -e ".[dev]"`, set `DATABASE_URL` to a local PostgreSQL URL, run `alembic upgrade head`, and start `uvicorn app.main:app --reload`. `python -m pytest` runs the tests. The `/app` code uses only operational models; answer-key tables are populated only by the loader and are never imported by the application package.

`ERP_CONNECTOR=synthetic` selects the PostgreSQL-backed connector. Set `ERP_CONNECTOR=sap_b1` to select the interface-complete SAP Business One Service Layer stub; its methods document the intended OPOR/POR1, OITW, OITM, and OCRD mappings and raise `NotImplementedError` until that integration is implemented. Evaluation code can pass `as_of` dates to the synthetic connector to replay history without reading later stock snapshots, forecasts, or supplier events.

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