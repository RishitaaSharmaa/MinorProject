"""Synthetic ERP connector backed by the application's SQLAlchemy tables."""

from datetime import date, datetime, time, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.base import AsOf, ERPConnector
from app.connectors.dto import DecisionDTO, StateEventDTO, SupplierTerms
from app.models import Commitment, Decision, Forecast, Item, Outcome, StateEvent, StockSnapshot, Supplier
from app.models.history import SupplierDelivery


class SyntheticERPConnector(ERPConnector):
    """Query synthetic procurement tables and return only Pydantic DTOs."""

    def __init__(self, session: Session) -> None:
        """Bind this adapter to a request- or evaluation-scoped session."""
        self._session = session

    def get_stock(self, item_id: str, as_of: AsOf = None) -> int:
        """Return the latest stock snapshot no later than `as_of`."""
        statement = select(StockSnapshot.qty_on_hand).where(StockSnapshot.item_id == item_id)
        if as_of is not None:
            statement = statement.where(StockSnapshot.date <= _date_limit(as_of))
        value = self._session.scalar(statement.order_by(StockSnapshot.date.desc()).limit(1))
        return int(value) if value is not None else 0

    def get_forecast(self, item_id: str, as_of: AsOf = None) -> float:
        """Return the most recent forecast week available by `as_of`."""
        statement = select(Forecast.forecast_qty).where(Forecast.item_id == item_id)
        if as_of is not None:
            statement = statement.where(Forecast.week <= _date_limit(as_of))
        value = self._session.scalar(statement.order_by(Forecast.week.desc()).limit(1))
        return float(value) if value is not None else 0.0

    def get_supplier_terms(self, supplier_id: str, as_of: AsOf = None) -> SupplierTerms:
        """Return supplier terms revised by state events available at `as_of`."""
        supplier = self._session.get(Supplier, supplier_id)
        if supplier is None:
            raise LookupError(f"Supplier not found: {supplier_id}")
        moq = self._session.scalar(
            select(func.min(Item.min_order_qty)).where(Item.primary_supplier_id == supplier_id)
        )
        quoted_lead_time = float(supplier.quoted_lead_time_days)
        price_break_tiers = list(supplier.price_break_tiers)
        strike_status = supplier.strike_status

        statement = select(StateEvent).where(
            StateEvent.entity_type == "supplier",
            StateEvent.entity_id == supplier_id,
        )
        if as_of is not None:
            statement = statement.where(StateEvent.event_time <= _datetime_limit(as_of))
        for event in self._session.scalars(statement.order_by(StateEvent.event_time.asc())):
            if event.field in {"lead_time_days", "quoted_lead_time_days"} and event.new_value is not None:
                quoted_lead_time = float(event.new_value)
            elif event.field == "price_break_tiers" and event.new_value is not None:
                price_break_tiers = list(event.new_value)
            elif event.field == "strike_status" and event.new_value is not None:
                strike_status = str(event.new_value)

        return SupplierTerms(
            supplier_id=supplier_id,
            as_of=as_of,
            quoted_lead_time=quoted_lead_time,
            moq=int(moq or 0),
            price_break_tiers=price_break_tiers,
            strike_status=strike_status,
            lead_time_std_dev=float(supplier.lead_time_std_dev),
            reliability_score=float(supplier.reliability_score),
        )

    def get_supplier_actual_lead_times(self, supplier_id: str, as_of: AsOf = None) -> list[float]:
        """Return completed PO-to-delivery durations known by the simulated date."""
        statement = (
            select(Decision.created_at, SupplierDelivery.actual_delivery_date)
            .join(SupplierDelivery, SupplierDelivery.decision_id == Decision.id)
            .where(SupplierDelivery.supplier_id == supplier_id)
        )
        if as_of is not None:
            statement = statement.where(SupplierDelivery.actual_delivery_date <= _date_limit(as_of))
        statement = statement.order_by(Decision.created_at.asc())
        return [
            float((actual_delivery - created_at.date()).days)
            for created_at, actual_delivery in self._session.execute(statement)
        ]

    def list_decisions(
        self, since: date | datetime | None = None, only_overrides: bool = False
    ) -> list[DecisionDTO]:
        """Return decisions filtered by creation time and override status."""
        statement = select(Decision)
        if since is not None:
            statement = statement.where(Decision.created_at >= _datetime_limit(since))
        if only_overrides:
            statement = statement.where(Decision.is_override.is_(True))
        statement = statement.order_by(Decision.created_at.asc(), Decision.id.asc())
        return [_decision_dto(decision) for decision in self._session.scalars(statement)]

    def get_decision(self, decision_id: str) -> DecisionDTO:
        """Return one detached decision DTO or raise `LookupError`."""
        decision = self._session.get(Decision, decision_id)
        if decision is None:
            raise LookupError(f"Decision not found: {decision_id}")
        return _decision_dto(decision)

    def list_state_events(self, since: date | datetime) -> list[StateEventDTO]:
        """Return state events on or after a given simulation timestamp."""
        statement = select(StateEvent).where(
            StateEvent.event_time >= _datetime_limit(since)
        ).order_by(StateEvent.event_time.asc(), StateEvent.id.asc())
        return [
            StateEventDTO(
                id=event.id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                field=event.field,
                old_value=event.old_value,
                new_value=event.new_value,
                event_time=event.event_time,
            )
            for event in self._session.scalars(statement)
        ]

    def write_outcome(self, decision_id: str, action: str, result: str) -> None:
        """Insert or update an observed decision outcome."""
        if self._session.get(Decision, decision_id) is None:
            raise LookupError(f"Decision not found: {decision_id}")
        outcome = self._session.scalar(select(Outcome).where(Outcome.decision_id == decision_id))
        now = datetime.now(timezone.utc)
        if outcome is None:
            self._session.add(Outcome(
                id=str(uuid4()),
                decision_id=decision_id,
                recommended_action="not_available",
                actual_action=action,
                actual_result=result,
                logged_at=now,
            ))
        else:
            outcome.actual_action = action
            outcome.actual_result = result
            outcome.logged_at = now
        self._session.commit()


def _date_limit(value: date | datetime) -> date:
    """Normalize a simulated timestamp to its calendar date."""
    return value.date() if isinstance(value, datetime) else value


def _datetime_limit(value: date | datetime) -> datetime:
    """Normalize date cutoffs to inclusive UTC midnight timestamps."""
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _decision_dto(decision: Decision) -> DecisionDTO:
    """Copy a SQLAlchemy decision into an ORM-independent DTO."""
    operational_fields = {
        key: value
        for key, value in decision.structured_fields.items()
        if key != "true_assumptions"
    }
    return DecisionDTO(
        id=decision.id,
        type=decision.decision_type,
        created_at=decision.created_at,
        structured_fields=operational_fields,
        free_text_reason=decision.free_text_reason,
        is_override=decision.is_override,
        status=decision.status,
        item_id=decision.item_id,
        supplier_id=decision.supplier_id,
        quantity=decision.quantity,
        unit_price=decision.unit_price,
        po_date=decision.po_date,
        expected_delivery=decision.expected_delivery,
    )