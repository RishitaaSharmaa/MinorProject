# Sharma Industries Synthetic Procurement Dataset

This project generates six months of daily procurement and inventory data for a fictional mid-sized Indian SME. The simulation is seeded; buyer notes are generated with Groq by default and are nondeterministic.

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