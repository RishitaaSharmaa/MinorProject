"""Mapping-driven import of any ERP's CSV export into the canonical procurement model.

An enterprise never has to reshape its data: it uploads whatever its ERP exports, maps
its column names to the canonical fields once (the mapping is saved), and gets a
validated preview before anything is written. The engine only ever sees canonical rows.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.models import (
    Commitment,
    Decision,
    ImportMapping,
    ImportRun,
    Item,
    StateEvent,
    StockSnapshot,
    Supplier,
)
from app.services.ingest import ingest_event

MAX_ROWS = 50_000
MAX_EVENT_ROWS = 5_000
MAX_ERRORS_REPORTED = 50
SAMPLE_ROWS = 10
_CHUNK = 400

DATE_FORMATS: dict[str, str | None] = {
    "auto": None,
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "DD-Mon-YYYY": "%d-%b-%Y",
    "YYYYMMDD": "%Y%m%d",
}
_EMPTY_TOKENS = {"", "null", "none", "n/a", "na", "nan", "-"}
_DEFAULT_TIERS = [{"min_qty": 1, "discount_pct": 0.0}]


class ImportFailure(ValueError):
    """The upload cannot be processed at all (as opposed to individual bad rows)."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # str | int | round | float | frac | date | datetime | bool | json | value
    required: bool = False
    default: Any = None
    description: str = ""
    synonyms: tuple[str, ...] = ()
    max_len: int | None = None
    minimum: float | None = None
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    title: str
    description: str
    key: str
    depends_on: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    max_rows: int = MAX_ROWS

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


DATASETS: dict[str, DatasetSpec] = {
    spec.name: spec
    for spec in (
        DatasetSpec(
            name="suppliers", title="Suppliers", key="supplier_id", depends_on=(),
            description="Vendor master data: quoted lead time, reliability and standing.",
            fields=(
                FieldSpec("supplier_id", "str", True, description="Unique vendor code", max_len=32,
                          synonyms=("vendorid", "vendorcode", "suppliercode", "vendorno", "lifnr", "id")),
                FieldSpec("name", "str", True, description="Vendor name", max_len=255,
                          synonyms=("vendorname", "suppliername", "company", "name1")),
                FieldSpec("quoted_lead_time_days", "int", True, minimum=0, description="Promised lead time in days",
                          synonyms=("leadtime", "leadtimedays", "ltdays", "quotedleadtime", "plifz")),
                FieldSpec("lead_time_std_dev", "float", default=0.0, minimum=0, description="Std. deviation of lead time (days)",
                          synonyms=("leadtimevariance", "leadtimestd")),
                FieldSpec("reliability_score", "frac", default=0.9, description="On-time delivery rate, 0-1 or %",
                          synonyms=("reliability", "ontimerate", "otif", "ontimedelivery")),
                FieldSpec("strike_status", "str", default="clear", max_len=32,
                          description="Standing, e.g. clear / watch / strike", synonyms=("status", "standing")),
                FieldSpec("price_break_tiers", "json", default=_DEFAULT_TIERS,
                          description='JSON list like [{"min_qty":100,"discount_pct":2}]',
                          synonyms=("pricetiers", "pricebreaks", "discounttiers")),
            ),
        ),
        DatasetSpec(
            name="items", title="Items / SKUs", key="item_id", depends_on=("suppliers",),
            description="Item master: cost, order minimum, preferred supplier and demand.",
            fields=(
                FieldSpec("item_id", "str", True, description="Unique SKU / material number", max_len=32,
                          synonyms=("sku", "itemcode", "material", "materialnumber", "partno", "productcode", "matnr", "id")),
                FieldSpec("name", "str", True, description="Item description", max_len=255,
                          synonyms=("description", "itemname", "materialdescription", "maktx", "productname")),
                FieldSpec("category", "str", default="General", max_len=128,
                          description="Category or material group", synonyms=("materialgroup", "group", "productgroup", "family")),
                FieldSpec("unit_cost", "float", True, minimum=0, description="Cost per unit",
                          synonyms=("cost", "standardcost", "price", "unitprice", "purchaseprice")),
                FieldSpec("holding_cost_pct", "frac", default=0.2, description="Annual holding cost, 0-1 or %",
                          synonyms=("holdingcost", "carryingcost", "holdingrate")),
                FieldSpec("min_order_qty", "int", default=1, minimum=1, description="Minimum order quantity",
                          synonyms=("moq", "minorderqty", "minimumorderquantity", "minbestell")),
                FieldSpec("primary_supplier_id", "str", True, max_len=32, description="Preferred supplier code",
                          synonyms=("supplierid", "vendorid", "preferredsupplier", "vendor", "supplier", "lifnr")),
                FieldSpec("avg_daily_demand", "round", default=0, minimum=0, description="Average units sold per day",
                          synonyms=("dailydemand", "avgdemand", "demandperday")),
                FieldSpec("reorder_point_qty", "round", default=0, minimum=0, description="Reorder point quantity",
                          synonyms=("reorderpoint", "rop", "reorderlevel", "minstock")),
            ),
        ),
        DatasetSpec(
            name="purchase_orders", title="Purchase orders", key="po_id", depends_on=("suppliers", "items"),
            description="Open and recent purchase orders. Add the planner's note to capture why it was placed.",
            fields=(
                FieldSpec("po_id", "str", True, max_len=64, description="Purchase order number",
                          synonyms=("ponumber", "pono", "orderid", "ordernumber", "purchaseorder", "ebeln", "id")),
                FieldSpec("item_id", "str", True, max_len=32, description="SKU ordered",
                          synonyms=("sku", "itemcode", "material", "partno", "matnr")),
                FieldSpec("supplier_id", "str", True, max_len=32, description="Vendor code",
                          synonyms=("vendorid", "vendorcode", "suppliercode", "vendor", "supplier", "lifnr")),
                FieldSpec("quantity", "int", True, minimum=1, description="Ordered quantity",
                          synonyms=("qty", "orderqty", "orderedquantity", "menge")),
                FieldSpec("unit_price", "float", True, minimum=0, description="Price per unit",
                          synonyms=("price", "unitcost", "netprice", "rate", "netpr")),
                FieldSpec("po_date", "date", True, description="Order date",
                          synonyms=("orderdate", "date", "createdon", "createdat", "bedat")),
                FieldSpec("expected_delivery", "date", description="Promised delivery date",
                          synonyms=("deliverydate", "duedate", "promiseddate", "eta", "eindt")),
                FieldSpec("free_text_reason", "str", description="Planner's note on why the order was placed or overridden",
                          synonyms=("reason", "note", "notes", "comment", "comments", "remarks", "justification")),
                FieldSpec("status", "str", default="placed", max_len=32, description="Order status", synonyms=("orderstatus", "state")),
                FieldSpec("is_override", "bool", description="True when the planner overrode the system suggestion (defaults to true if a note is given)",
                          synonyms=("override", "overridden", "manualoverride")),
                FieldSpec("cancellation_fee_pct", "frac", description="Cancellation fee, 0-1 or % (needs reversible_until)",
                          synonyms=("cancellationfee", "cancelfee", "cancelpenalty")),
                FieldSpec("reversible_until", "date", description="Last date the order can be cancelled or changed",
                          synonyms=("cancellabledate", "cancelby", "freezedate", "lockdate", "changeuntil")),
            ),
        ),
        DatasetSpec(
            name="stock_levels", title="Stock levels", key="item_id + date", depends_on=("items",),
            description="On-hand quantity per item and day. The latest row per item also triggers assumption checks.",
            fields=(
                FieldSpec("item_id", "str", True, max_len=32, description="SKU",
                          synonyms=("sku", "itemcode", "material", "partno", "matnr")),
                FieldSpec("date", "date", True, description="Snapshot date",
                          synonyms=("snapshotdate", "asof", "asofdate", "stockdate", "day")),
                FieldSpec("qty_on_hand", "round", True, minimum=0, description="Quantity on hand",
                          synonyms=("stock", "qty", "onhand", "quantity", "stockqty", "unrestricted", "labst")),
            ),
        ),
        DatasetSpec(
            name="state_events", title="Changes / events", key="id", depends_on=("items", "suppliers"),
            description="Any change worth watching, e.g. a supplier's lead time or an item's stock. Checked against assumptions immediately.",
            max_rows=MAX_EVENT_ROWS,
            fields=(
                FieldSpec("entity_type", "str", True, choices=("item", "supplier"), description="item or supplier",
                          synonyms=("entity", "type", "kind")),
                FieldSpec("entity_id", "str", True, max_len=255, description="SKU or vendor code",
                          synonyms=("entityref", "code")),
                FieldSpec("field", "str", True, max_len=128, description="e.g. stock_qty, lead_time_days, strike_status",
                          synonyms=("attribute", "property", "metric")),
                FieldSpec("new_value", "value", True, description="The new value",
                          synonyms=("value", "newvalue", "to")),
                FieldSpec("event_time", "datetime", description="When it changed (defaults to now)",
                          synonyms=("time", "timestamp", "date", "changedon", "changedat")),
                FieldSpec("event_id", "str", max_len=64, description="Idempotency key; re-uploading the same id is skipped",
                          synonyms=("eventid", "uid", "reference")),
            ),
        ),
    )
}


@dataclass(frozen=True)
class RowError:
    row: int
    field: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass
class Analysis:
    dataset: str
    headers: list[str]
    suggested_mapping: dict[str, str]
    mapping: dict[str, str]
    missing_required: list[str]
    total_rows: int
    rows: list[dict[str, Any]] = dc_field(default_factory=list)
    errors: list[RowError] = dc_field(default_factory=list)

    @property
    def error_rows(self) -> int:
        return len({e.row for e in self.errors})


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _detect_delimiter(text: str) -> str:
    """Pick the delimiter that appears most in the header line (outside quotes); default comma."""
    header = next((line for line in text.splitlines() if line.strip()), "")
    header = re.sub(r'"[^"]*"', "", header)
    counts = {d: header.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def parse_csv(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Return headers and (line_number, row) pairs, skipping blank lines."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise ImportFailure("The file is empty")
    reader = csv.reader(io.StringIO(text), delimiter=_detect_delimiter(text))
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration as exc:
        raise ImportFailure("The file is empty") from exc
    if not any(headers) or "" in headers:
        raise ImportFailure("The first row must be column headers, and none may be blank")
    if len({h.lower() for h in headers}) != len(headers):
        raise ImportFailure("Column headers must be unique")
    rows: list[tuple[int, dict[str, str]]] = []
    for line, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        rows.append((line, {h: (values[i].strip() if i < len(values) else "") for i, h in enumerate(headers)}))
    return headers, rows


def suggest_mapping(spec: DatasetSpec, headers: list[str]) -> dict[str, str]:
    """Match headers to canonical fields by normalised name or known synonym."""
    normalised = {header: _norm(header) for header in headers}
    taken: set[str] = set()
    mapping: dict[str, str] = {}
    for spec_field in spec.fields:
        candidates = [_norm(spec_field.name), *spec_field.synonyms]
        for candidate in candidates:
            match = next((h for h, n in normalised.items() if n == candidate and h not in taken), None)
            if match:
                mapping[spec_field.name] = match
                taken.add(match)
                break
    return mapping


def _is_empty(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in _EMPTY_TOKENS


def _number(raw: str) -> float:
    text = raw.strip()
    negative = text.startswith("(") and text.endswith(")")
    percent = text.endswith("%")
    match = re.fullmatch(r"[^\d\-+.,]*([-+]?[\d.,]+)[^\d\-+.,]*", text)
    if not match:
        raise ValueError("not a number")
    text = match.group(1)
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+", text) or re.fullmatch(r"[-+]?\d{1,2}(,\d{2})+,\d{3}", text):
            text = text.replace(",", "")
        elif text.count(",") == 1:
            text = text.replace(",", ".")
        else:
            raise ValueError("not a number")
    value = float(text)
    if negative:
        value = -value
    return value / 100 if percent else value


def _parse_date(raw: str, date_format: str | None) -> date:
    text = raw.strip()
    if date_format:
        for candidate in (text, re.split(r"[T ]", text)[0]):
            try:
                return datetime.strptime(candidate, date_format).date()
            except ValueError:
                continue
        raise ValueError(f"does not match the date format {date_format}")
    match = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", text)
    if match:
        return date(int(match[1]), int(match[2]), int(match[3]))
    raise ValueError("unrecognised date; choose a date format that matches your file")


def _convert(spec_field: FieldSpec, raw: str, date_format: str | None) -> Any:
    kind = spec_field.kind
    if kind == "str":
        value = raw.strip()
        if spec_field.max_len and len(value) > spec_field.max_len:
            raise ValueError(f"longer than {spec_field.max_len} characters")
        if spec_field.choices and value.lower() not in spec_field.choices:
            raise ValueError(f"must be one of {', '.join(spec_field.choices)}")
        return value.lower() if spec_field.choices else value
    if kind in {"int", "round", "float", "frac"}:
        try:
            number = _number(raw)
        except ValueError as exc:
            raise ValueError(f"{raw!r} is not a number") from exc
        if kind == "frac":
            if number > 1:
                number /= 100
            if not 0 <= number <= 1:
                raise ValueError("must be between 0 and 1 (or 0% and 100%)")
        elif kind == "int":
            if abs(number - round(number)) > 1e-9:
                raise ValueError("must be a whole number")
            number = int(round(number))
        elif kind == "round":
            number = int(round(number))
        if spec_field.minimum is not None and number < spec_field.minimum:
            raise ValueError(f"must be at least {spec_field.minimum:g}")
        return number
    if kind == "date":
        return _parse_date(raw, date_format)
    if kind == "datetime":
        text = raw.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            day = _parse_date(text, date_format)
            return datetime.combine(day, time.min)
    if kind == "bool":
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "y", "t"}:
            return True
        if lowered in {"false", "0", "no", "n", "f"}:
            return False
        raise ValueError("must be yes/no or true/false")
    if kind == "json":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("is not valid JSON") from exc
        if not (
            isinstance(value, list) and value
            and all(isinstance(t, dict) and {"min_qty", "discount_pct"} <= t.keys() for t in value)
        ):
            raise ValueError('must be a list of {"min_qty", "discount_pct"} objects')
        return value
    if kind == "value":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
    raise ValueError(f"unsupported field kind {kind}")


def _existing(session: Session, column: Any, values: set[Any]) -> set[Any]:
    found: set[Any] = set()
    ordered = list(values)
    for start in range(0, len(ordered), _CHUNK):
        found.update(session.scalars(select(column).where(column.in_(ordered[start:start + _CHUNK]))))
    return found


def _check_references(session: Session, dataset: str, rows: list[dict[str, Any]]) -> list[RowError]:
    """Flag rows pointing at items or suppliers that do not exist yet."""
    checks: list[tuple[str, Any, str]] = []
    if dataset == "items":
        checks = [("primary_supplier_id", Supplier.id, "supplier")]
    elif dataset == "purchase_orders":
        checks = [("item_id", Item.id, "item"), ("supplier_id", Supplier.id, "supplier")]
    elif dataset == "stock_levels":
        checks = [("item_id", Item.id, "item")]
    errors: list[RowError] = []
    for name, column, label in checks:
        known = _existing(session, column, {r[name] for r in rows})
        for row in rows:
            if row[name] not in known:
                errors.append(RowError(row["_row"], name, f"unknown {label} {row[name]!r}; import {label}s first"))
    if dataset == "state_events":
        for entity_type, column in (("item", Item.id), ("supplier", Supplier.id)):
            scoped = [r for r in rows if r["entity_type"] == entity_type]
            known = _existing(session, column, {r["entity_id"] for r in scoped})
            errors += [
                RowError(r["_row"], "entity_id", f"unknown {entity_type} {r['entity_id']!r}")
                for r in scoped if r["entity_id"] not in known
            ]
    return errors


def _key(dataset: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return {
        "suppliers": lambda r: (r["supplier_id"],),
        "items": lambda r: (r["item_id"],),
        "purchase_orders": lambda r: (r["po_id"],),
        "stock_levels": lambda r: (r["item_id"], r["date"]),
    }.get(dataset, lambda r: (r["_row"],))(row)


def analyze(
    session: Session, dataset: str, csv_text: str,
    mapping: dict[str, str] | None = None, date_format: str | None = None,
) -> Analysis:
    """Parse, map and validate an upload without writing anything."""
    spec = DATASETS.get(dataset)
    if spec is None:
        raise ImportFailure(f"Unknown dataset {dataset!r}")
    if date_format is not None and date_format not in DATE_FORMATS:
        raise ImportFailure(f"Unknown date format {date_format!r}")
    strptime_format = DATE_FORMATS.get(date_format or "auto")
    headers, parsed = parse_csv(csv_text)
    if len(parsed) > spec.max_rows:
        raise ImportFailure(f"Too many rows: {len(parsed)} (limit {spec.max_rows} per upload for {spec.title})")

    suggested = suggest_mapping(spec, headers)
    if mapping is None:
        mapping = suggested
    valid_fields = {f.name for f in spec.fields}
    for name, column in mapping.items():
        if name not in valid_fields:
            raise ImportFailure(f"Unknown field {name!r} in mapping")
        if column not in headers:
            raise ImportFailure(f"Mapped column {column!r} is not in the file")
    missing = [f.name for f in spec.fields if f.required and f.name not in mapping]
    analysis = Analysis(
        dataset=dataset, headers=headers, suggested_mapping=suggested, mapping=dict(mapping),
        missing_required=missing, total_rows=len(parsed),
    )
    if missing:
        return analysis

    seen: dict[tuple[Any, ...], int] = {}
    for line, raw_row in parsed:
        out: dict[str, Any] = {"_row": line}
        problems: list[RowError] = []
        for spec_field in spec.fields:
            column = mapping.get(spec_field.name)
            raw = raw_row.get(column) if column else None
            empty = _is_empty(raw) if spec_field.kind != "str" else not (raw or "").strip()
            if empty:
                if spec_field.required:
                    problems.append(RowError(line, spec_field.name, "is required"))
                else:
                    out[spec_field.name] = spec_field.default
                continue
            try:
                out[spec_field.name] = _convert(spec_field, raw, strptime_format)
            except ValueError as exc:
                problems.append(RowError(line, spec_field.name, str(exc)))
        if not problems and dataset == "purchase_orders":
            if (out["cancellation_fee_pct"] is None) != (out["reversible_until"] is None):
                problems.append(RowError(line, "reversible_until", "cancellation_fee_pct and reversible_until must be given together"))
        if not problems:
            key = _key(dataset, out)
            if key in seen:
                problems.append(RowError(line, None, f"duplicate of row {seen[key]}"))
            else:
                seen[key] = line
        if problems:
            analysis.errors += problems
        else:
            analysis.rows.append(out)

    reference_errors = _check_references(session, dataset, analysis.rows)
    if reference_errors:
        bad = {e.row for e in reference_errors}
        analysis.errors += reference_errors
        analysis.rows = [r for r in analysis.rows if r["_row"] not in bad]
    analysis.errors.sort(key=lambda e: (e.row, e.field or ""))
    return analysis


def sample_rows(analysis: Analysis) -> list[dict[str, Any]]:
    """JSON-safe preview of the first mapped rows."""
    def plain(value: Any) -> Any:
        return value.isoformat() if isinstance(value, (date, datetime)) else value
    return [
        {k: plain(v) for k, v in row.items() if not k.startswith("_")}
        for row in analysis.rows[:SAMPLE_ROWS]
    ]


def get_saved_mapping(session: Session, dataset: str) -> ImportMapping | None:
    return session.get(ImportMapping, dataset)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _upsert(session: Session, model: Any, key_attr: str, payloads: list[dict[str, Any]]) -> tuple[int, int]:
    column = getattr(model, key_attr)
    known = _existing(session, column, {p[key_attr] for p in payloads})
    fresh = [p for p in payloads if p[key_attr] not in known]
    if fresh:
        session.execute(insert(model), fresh)
    for payload in payloads:
        if payload[key_attr] in known:
            session.execute(
                update(model).where(column == payload[key_attr])
                .values(**{k: v for k, v in payload.items() if k != key_attr})
            )
    return len(fresh), len(payloads) - len(fresh)


def _write_decisions(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    payloads = []
    commitments = []
    for r in rows:
        fields = {
            "item_id": r["item_id"], "supplier_id": r["supplier_id"],
            "order_qty": r["quantity"], "unit_cost": r["unit_price"],
        }
        payloads.append({
            "id": r["po_id"], "decision_type": "purchase_order", "created_at": _midnight(r["po_date"]),
            "structured_fields": fields, "free_text_reason": r["free_text_reason"] or None,
            "is_override": r["is_override"] if r["is_override"] is not None else bool(r["free_text_reason"]),
            "status": r["status"], "item_id": r["item_id"], "supplier_id": r["supplier_id"],
            "quantity": r["quantity"], "unit_price": r["unit_price"],
            "po_date": r["po_date"], "expected_delivery": r["expected_delivery"],
        })
        if r["cancellation_fee_pct"] is not None:
            commitments.append({
                "id": f"COM-{r['po_id']}"[:64], "decision_id": r["po_id"],
                "cancellation_fee_pct": r["cancellation_fee_pct"], "reversible_until": r["reversible_until"],
            })
    inserted, updated = _upsert(session, Decision, "id", payloads)
    if commitments:
        _upsert(session, Commitment, "id", commitments)
    return inserted, updated


def _write_stock(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    pairs: set[tuple[str, date]] = set()
    items = sorted({r["item_id"] for r in rows})
    for start in range(0, len(items), _CHUNK):
        pairs.update(
            (i, d) for i, d in session.execute(
                select(StockSnapshot.item_id, StockSnapshot.date)
                .where(StockSnapshot.item_id.in_(items[start:start + _CHUNK]))
            )
        )
    fresh = [
        {"item_id": r["item_id"], "date": r["date"], "qty_on_hand": r["qty_on_hand"]}
        for r in rows if (r["item_id"], r["date"]) not in pairs
    ]
    changed = [r for r in rows if (r["item_id"], r["date"]) in pairs]
    if fresh:
        session.execute(insert(StockSnapshot), fresh)
    for r in changed:
        session.execute(
            update(StockSnapshot)
            .where(StockSnapshot.item_id == r["item_id"], StockSnapshot.date == r["date"])
            .values(qty_on_hand=r["qty_on_hand"])
        )
    session.commit()

    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["item_id"] not in latest or r["date"] > latest[r["item_id"]]["date"]:
            latest[r["item_id"]] = r
    flagged: set[str] = set()
    for r in latest.values():
        result = ingest_event(
            session, entity_type="item", entity_id=r["item_id"], field_name="stock_qty",
            new_value=r["qty_on_hand"], event_time=_midnight(r["date"]),
            event_id=f"imp-stock-{r['item_id']}-{r['date'].isoformat()}"[:64],
        )
        flagged.update(result.violated_decision_ids)
    return len(fresh), len(changed), len(flagged)


def _write_events(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    inserted = duplicates = 0
    flagged: set[str] = set()
    for r in rows:
        when = r["event_time"] or datetime.now(timezone.utc)
        digest = hashlib.sha1(
            f"{r['entity_type']}|{r['entity_id']}|{r['field']}|{r['new_value']}|{when.isoformat()}".encode()
        ).hexdigest()[:40]
        result = ingest_event(
            session, entity_type=r["entity_type"], entity_id=r["entity_id"], field_name=r["field"],
            new_value=r["new_value"], event_time=when, event_id=r["event_id"] or f"imp-{digest}",
        )
        if result.duplicate:
            duplicates += 1
        else:
            inserted += 1
            flagged.update(result.violated_decision_ids)
    return inserted, duplicates, len(flagged)


def commit_import(
    session: Session, analysis: Analysis, *, filename: str | None = None,
    date_format: str | None = None, skip_invalid: bool = False, remember_mapping: bool = True,
) -> ImportRun:
    """Write the valid rows, remember the mapping and log the run."""
    if analysis.missing_required:
        raise ImportFailure(f"Map every required field first: {', '.join(analysis.missing_required)}")
    if analysis.errors and not skip_invalid:
        raise ImportFailure(
            f"{analysis.error_rows} row(s) have errors. Fix the file, or import only the valid rows."
        )
    rows = [{k: v for k, v in r.items()} for r in analysis.rows]
    dataset = analysis.dataset
    flagged = 0
    if rows:
        if dataset == "suppliers":
            _upsert(session, Supplier, "id", [{
                "id": r["supplier_id"], "name": r["name"],
                "quoted_lead_time_days": r["quoted_lead_time_days"], "lead_time_std_dev": r["lead_time_std_dev"],
                "reliability_score": r["reliability_score"], "price_break_tiers": r["price_break_tiers"],
                "strike_status": r["strike_status"],
            } for r in rows])
        elif dataset == "items":
            _upsert(session, Item, "id", [{
                "id": r["item_id"], "name": r["name"], "category": r["category"], "unit_cost": r["unit_cost"],
                "holding_cost_pct": r["holding_cost_pct"], "min_order_qty": r["min_order_qty"],
                "primary_supplier_id": r["primary_supplier_id"], "avg_daily_demand": r["avg_daily_demand"],
                "reorder_point_qty": r["reorder_point_qty"],
            } for r in rows])
        elif dataset == "purchase_orders":
            _write_decisions(session, rows)
        elif dataset == "stock_levels":
            flagged = _write_stock(session, rows)[2]
        elif dataset == "state_events":
            flagged = _write_events(session, rows)[2]

    now = datetime.now(timezone.utc)
    if remember_mapping:
        saved = session.get(ImportMapping, dataset)
        if saved is None:
            session.add(ImportMapping(dataset=dataset, mapping=analysis.mapping, date_format=date_format, updated_at=now))
        else:
            saved.mapping, saved.date_format, saved.updated_at = analysis.mapping, date_format, now
    run = ImportRun(
        id=str(uuid4()), dataset=dataset, filename=(filename or None) and filename[:255],
        rows_total=analysis.total_rows, rows_imported=len(rows), rows_rejected=analysis.error_rows,
        decisions_flagged=flagged, errors_sample=[e.as_dict() for e in analysis.errors[:MAX_ERRORS_REPORTED]],
        created_at=now,
    )
    session.add(run)
    session.commit()
    return run
