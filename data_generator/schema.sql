CREATE TABLE items (
    item_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_cost NUMERIC(12, 2) NOT NULL,
    holding_cost_pct NUMERIC(6, 3) NOT NULL,
    min_order_qty INTEGER NOT NULL,
    primary_supplier_id TEXT NOT NULL,
    avg_daily_demand INTEGER NOT NULL,
    reorder_point_qty INTEGER NOT NULL
);

CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    quoted_lead_time_days INTEGER NOT NULL,
    lead_time_std_dev NUMERIC(6, 2) NOT NULL,
    reliability_score NUMERIC(5, 3) NOT NULL,
    price_break_tiers JSONB NOT NULL,
    strike_status TEXT NOT NULL
);

CREATE TABLE sales_history (
    item_id TEXT NOT NULL REFERENCES items(item_id),
    date DATE NOT NULL,
    qty_sold INTEGER NOT NULL,
    PRIMARY KEY (item_id, date)
);

CREATE TABLE stock_snapshot (
    item_id TEXT NOT NULL REFERENCES items(item_id),
    date DATE NOT NULL,
    qty_on_hand INTEGER NOT NULL,
    PRIMARY KEY (item_id, date)
);

CREATE TABLE weekly_forecasts (
    item_id TEXT NOT NULL REFERENCES items(item_id),
    week DATE NOT NULL,
    forecast_qty INTEGER NOT NULL,
    true_demand INTEGER NOT NULL,
    forecast_error_pct NUMERIC(8, 5) NOT NULL,
    PRIMARY KEY (item_id, week)
);

CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    created_at DATE NOT NULL,
    structured_fields JSONB NOT NULL,
    free_text_reason TEXT,
    is_override BOOLEAN NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE assumptions (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    condition JSONB NOT NULL,
    is_ground_truth BOOLEAN NOT NULL,
    confirmed_by_user BOOLEAN NOT NULL
);

CREATE TABLE supplier_delivery_history (
    decision_id TEXT PRIMARY KEY REFERENCES decisions(id),
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    promised_delivery_date DATE NOT NULL,
    actual_delivery_date DATE NOT NULL,
    delay_days INTEGER NOT NULL,
    arrived_late BOOLEAN NOT NULL
);

CREATE TABLE state_events (
    id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    event_time DATE NOT NULL,
    event_type TEXT NOT NULL
);

CREATE TABLE ground_truth_violations (
    event_id TEXT NOT NULL REFERENCES state_events(id),
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    violated_condition JSONB NOT NULL,
    event_date DATE NOT NULL,
    PRIMARY KEY (event_id, decision_id, violated_condition)
);

CREATE TABLE commitments (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id),
    cancellation_fee_pct NUMERIC(6, 3) NOT NULL,
    reversible_until_date DATE NOT NULL,
    linked_commitment_id TEXT REFERENCES commitments(id)
);

CREATE TABLE commitment_links (
    id TEXT PRIMARY KEY,
    from_commitment_id TEXT NOT NULL REFERENCES commitments(id),
    to_commitment_id TEXT NOT NULL REFERENCES commitments(id),
    link_type TEXT NOT NULL DEFAULT 'other',
    savings_at_stake NUMERIC(12, 2) NOT NULL DEFAULT 0,
    UNIQUE (from_commitment_id, to_commitment_id),
    CHECK (from_commitment_id <> to_commitment_id),
    CHECK (link_type IN ('freight_consolidation', 'volume_discount', 'moq_pool', 'bundled_shipment', 'other'))
);

CREATE TABLE outcomes (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id),
    recommended_action TEXT NOT NULL,
    actual_action TEXT NOT NULL,
    actual_result TEXT NOT NULL
);

CREATE TABLE baseline_event_flags (
    event_id TEXT NOT NULL REFERENCES state_events(id),
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    flag_reason TEXT NOT NULL,
    PRIMARY KEY (event_id, decision_id)
);