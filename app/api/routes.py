"""Decision review, brief, and metrics routes for the backend API."""

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ActionCostOut,
    AssumptionOut,
    BriefCardOut,
    BriefResponse,
    ConfirmAssumptionsRequest,
    ConfirmAssumptionsResponse,
    DecisionActionRequest,
    DecisionActionResponse,
    DecisionDetailResponse,
    DecisionScoreOut,
    MetricsResponse,
    RecheckResponse,
    SuggestionResponse,
    TimelineEventOut,
)
from app.connectors.factory import get_connector
from app.db import get_db
from app.models import Assumption, AssumptionProposal, Decision, StateEvent
from app.services.brief import generate_brief
from app.services.conditions import Condition, ProposedCondition
from app.services.extraction import extract_assumptions
from app.services.metrics import compute_metrics
from app.services.reasoning import explain_score
from app.services.watcher_runner import recheck_assumptions
from app.services.scoring import DecisionScore, score_decision
from app.services.suggestion import SuggestionUnavailable, suggest_action

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return process liveness without depending on database availability."""
    return {"status": "ok"}


@router.post("/decisions/{decision_id}/extract", response_model=list[ProposedCondition])
def extract_decision_assumptions(
    decision_id: str,
    session: Session = Depends(get_db),
) -> list[ProposedCondition]:
    """Extract and persist structured and free-text assumption proposals."""
    connector = get_connector(session)
    try:
        decision = connector.get_decision(decision_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposals = extract_assumptions(decision, connector)
    now = datetime.now(timezone.utc)
    for proposal in proposals:
        condition = proposal.model_dump(
            include={"type", "entity_ref", "op", "value", "needs_value_from_planner"},
            mode="json",
        )
        session.add(AssumptionProposal(
            id=proposal.proposal_id,
            decision_id=decision_id,
            condition=condition,
            source=proposal.source,
            confidence=proposal.confidence,
            warnings=proposal.warnings,
            review_status="pending",
            created_at=now,
        ))
    session.commit()
    return proposals


@router.post(
    "/decisions/{decision_id}/assumptions/confirm",
    response_model=ConfirmAssumptionsResponse,
)
def confirm_decision_assumptions(
    decision_id: str,
    payload: ConfirmAssumptionsRequest,
    session: Session = Depends(get_db),
) -> ConfirmAssumptionsResponse:
    """Store accepted planner edits and dispositions for all reviewed proposals."""
    accepted_ids = [entry.proposal_id for entry in payload.accepted]
    reviewed_ids = accepted_ids + payload.rejected_proposal_ids
    if len(reviewed_ids) != len(set(reviewed_ids)):
        raise HTTPException(status_code=422, detail="A proposal can only be reviewed once per request")
    if not reviewed_ids:
        raise HTTPException(status_code=422, detail="At least one proposal must be accepted or rejected")

    records = list(session.scalars(select(AssumptionProposal).where(
        AssumptionProposal.decision_id == decision_id,
        AssumptionProposal.id.in_(reviewed_ids),
    )))
    by_id = {record.id: record for record in records}
    if set(by_id) != set(reviewed_ids):
        raise HTTPException(status_code=404, detail="One or more proposals were not found for this decision")
    if any(record.review_status != "pending" for record in records):
        raise HTTPException(status_code=409, detail="One or more proposals have already been reviewed")

    accepted_count = 0
    edited_count = 0
    assumption_ids: list[str] = []
    now = datetime.now(timezone.utc)
    for accepted in payload.accepted:
        proposal = by_id[accepted.proposal_id]
        final_condition = accepted.condition.model_dump(mode="json")
        original_condition = Condition.model_validate(proposal.condition).model_dump(mode="json")
        disposition = "edited" if final_condition != original_condition else "accepted"
        proposal.review_status = disposition
        proposal.final_condition = final_condition
        proposal.reviewed_at = now
        assumption_id = str(uuid4())
        assumption_ids.append(assumption_id)
        session.add(Assumption(
            id=assumption_id,
            decision_id=decision_id,
            condition=final_condition,
            source=proposal.source,
            confirmed_by_user=True,
            status="live",
            created_at=now,
        ))
        accepted_count += 1
        edited_count += disposition == "edited"

    for proposal_id in payload.rejected_proposal_ids:
        proposal = by_id[proposal_id]
        proposal.review_status = "rejected"
        proposal.reviewed_at = now

    session.commit()
    return ConfirmAssumptionsResponse(
        accepted_count=accepted_count,
        edited_count=edited_count,
        rejected_count=len(payload.rejected_proposal_ids),
        assumption_ids=assumption_ids,
    )


@router.post("/events/recheck", response_model=RecheckResponse)
def recheck_events(
    as_of: date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> RecheckResponse:
    """Replay recorded state events and refresh every assumption's status for one date.

    Confirming an assumption does not, by itself, change its status: only a
    recheck pass can detect that a later event broke it. Call this before
    reading `/brief`, `/decisions/{id}`, or `/metrics` for a given `as_of` to
    make sure their view of `Assumption.status` reflects that date.
    """
    summary = recheck_assumptions(session, as_of or date.today())
    return RecheckResponse(
        as_of=summary.as_of,
        events_processed=summary.events_processed,
        assumptions_rechecked=summary.assumptions_rechecked,
        violations=summary.violations,
        recoveries=summary.recoveries,
    )


@router.get("/brief", response_model=BriefResponse)
def get_brief(
    as_of: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    explain: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> BriefResponse:
    """Return the ranked, deterministic action brief for one simulated date."""
    connector = get_connector(session)
    brief = generate_brief(session, connector, as_of or date.today(), limit=limit, explain=explain)
    return BriefResponse(
        as_of=brief.as_of,
        cards=[BriefCardOut(score=_score_out(card.score), explanation=card.explanation) for card in brief.cards],
        reviewed_and_kept=brief.reviewed_and_kept,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionDetailResponse)
def get_decision_detail(
    decision_id: str,
    as_of: date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> DecisionDetailResponse:
    """Return one decision's facts, assumptions, timeline, and current score."""
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision not found: {decision_id}")
    effective_as_of = as_of or date.today()

    assumptions = list(session.scalars(select(Assumption).where(Assumption.decision_id == decision_id)))
    score = _current_score(session, decision, assumptions, effective_as_of)
    events = _timeline_events(session, decision)

    return DecisionDetailResponse(
        id=decision.id,
        decision_type=decision.decision_type,
        created_at=decision.created_at,
        item_id=decision.item_id,
        supplier_id=decision.supplier_id,
        quantity=decision.quantity,
        unit_price=decision.unit_price,
        po_date=decision.po_date,
        expected_delivery=decision.expected_delivery,
        free_text_reason=decision.free_text_reason,
        is_override=decision.is_override,
        status=decision.status,
        assumptions=[
            AssumptionOut(
                id=assumption.id, condition=assumption.condition, source=assumption.source,
                status=assumption.status, confirmed_by_user=assumption.confirmed_by_user,
                created_at=assumption.created_at,
            )
            for assumption in assumptions
        ],
        timeline=[
            TimelineEventOut(
                id=event.id, entity_type=event.entity_type, entity_id=event.entity_id, field=event.field,
                old_value=event.old_value, new_value=event.new_value, event_time=event.event_time,
            )
            for event in events
        ],
        score=_score_out(score) if score is not None else None,
    )


@router.post("/decisions/{decision_id}/suggestion", response_model=SuggestionResponse)
def suggest_decision_action(
    decision_id: str,
    as_of: date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> SuggestionResponse:
    """Return an advisory LLM suggestion for a decision whose assumption has broken.

    Call `/events/recheck` for the same `as_of` first, as with `/decisions/{id}`.
    """
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision not found: {decision_id}")
    assumptions = list(session.scalars(select(Assumption).where(Assumption.decision_id == decision_id)))
    score = _current_score(session, decision, assumptions, as_of or date.today())
    if score is None:
        raise HTTPException(status_code=409, detail="This decision has no broken assumption, so there is nothing to suggest.")
    try:
        suggestion = suggest_action(decision, score, _timeline_events(session, decision))
    except SuggestionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SuggestionResponse(
        decision_id=suggestion.decision_id,
        suggested_action=suggestion.suggested_action,
        model_recommendation=suggestion.model_recommendation,
        agrees_with_model=suggestion.agrees_with_model,
        headline=suggestion.headline,
        rationale=suggestion.rationale,
        risks=list(suggestion.risks),
        next_steps=list(suggestion.next_steps),
    )


@router.post("/decisions/{decision_id}/action", response_model=DecisionActionResponse)
def act_on_decision(
    decision_id: str,
    payload: DecisionActionRequest,
    session: Session = Depends(get_db),
) -> DecisionActionResponse:
    """Record a planner's disposition of a decision and log the outcome via the connector."""
    connector = get_connector(session)
    try:
        connector.write_outcome(decision_id, payload.action, payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DecisionActionResponse(decision_id=decision_id, action=payload.action, note=payload.note)


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    as_of: date | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MetricsResponse:
    """Return operational review metrics as of one simulated date."""
    connector = get_connector(session)
    metrics = compute_metrics(session, connector, as_of or date.today())
    return MetricsResponse(
        flags_per_week=metrics.flags_per_week,
        action_rate=metrics.action_rate,
        extraction_correction_rate=metrics.extraction_correction_rate,
    )


def _current_score(
    session: Session, decision: Decision, assumptions: list[Assumption], as_of: date,
) -> DecisionScore | None:
    """Score a decision against its first violated assumption, if it has one."""
    violated = next((assumption for assumption in assumptions if assumption.status == "violated"), None)
    if violated is None:
        return None
    return score_decision(session, get_connector(session), decision, violated, as_of)


def _timeline_events(session: Session, decision: Decision) -> list[StateEvent]:
    """Return recorded state changes for the decision's item and supplier, oldest first."""
    timeline_filters = []
    if decision.item_id:
        timeline_filters.append((StateEvent.entity_type == "item") & (StateEvent.entity_id == decision.item_id))
    if decision.supplier_id:
        timeline_filters.append(
            (StateEvent.entity_type == "supplier") & (StateEvent.entity_id == decision.supplier_id)
        )
    if not timeline_filters:
        return []
    return list(session.scalars(
        select(StateEvent).where(or_(*timeline_filters)).order_by(StateEvent.event_time.asc())
    ))


def _score_out(score: DecisionScore) -> DecisionScoreOut:
    """Convert a scoring dataclass into its API response schema."""
    return DecisionScoreOut(
        decision_id=score.decision_id,
        assumption_id=score.assumption_id,
        order_value=score.order_value,
        cost_keep=score.cost_keep,
        cost_keep_breakdown=score.cost_keep_breakdown,
        actions={
            name: ActionCostOut(
                action=cost.action, residual_cost=cost.residual_cost, fee=cost.fee,
                in_transit=cost.in_transit, sibling_impact=cost.sibling_impact,
                switching_cost=cost.switching_cost, total_cost=cost.total_cost,
            )
            for name, cost in score.actions.items()
        },
        best_alternative=score.best_alternative,
        regret=score.regret,
        switching_cost=score.switching_cost,
        switching_cost_breakdown=score.switching_cost_breakdown,
        net_benefit=score.net_benefit,
        days_to_window=score.days_to_window,
        window_open=score.window_open,
        flagged=score.flagged,
        recommendation=score.recommendation,
        confidence=score.confidence,
        confidence_reasons=list(score.confidence_reasons),
        assumptions_used=score.assumptions_used,
        reasoning=explain_score(score),
    )