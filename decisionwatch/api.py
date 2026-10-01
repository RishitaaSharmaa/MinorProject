"""FastAPI endpoints for recording decisions and rechecking state changes."""

import json
from typing import Annotated, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from decisionwatch.database import get_session
from decisionwatch.erp import ERPConnector, InMemoryERPConnector
from decisionwatch.llm.client import LLMClient
from decisionwatch.models import ConditionRecord, DecisionLinkRecord, DecisionRecord, StateEventRecord
from decisionwatch.schemas import (
    DecisionCreate,
    DecisionLinkInput,
    DecisionOutput,
    DecisionReviewOutput,
    ExplanationOutput,
    ExtractionInput,
    ExtractionOutput,
    StateChangeInput,
)
from decisionwatch.services import persist_review

SessionDependency = Annotated[Session, Depends(get_session)]


def get_connector(request: Request) -> ERPConnector:
    """Return the configured ERP connector from application state."""
    return cast(ERPConnector, request.app.state.erp_connector)


def create_app(connector: ERPConnector | None = None) -> FastAPI:
    """Create the DecisionWatch API with an injectable ERP connector."""
    application = FastAPI(title="DecisionWatch", version="0.1.0")
    application.state.erp_connector = connector or InMemoryERPConnector()

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report API process health without touching the database."""
        return {"status": "ok"}

    @application.post("/decisions", response_model=DecisionOutput, status_code=status.HTTP_201_CREATED)
    def create_decision(payload: DecisionCreate, session: SessionDependency) -> DecisionRecord:
        """Persist a decision and its structured reasons."""
        decision = DecisionRecord(
            id=str(uuid4()),
            decision_type=payload.decision_type,
            created_at=payload.created_at,
            reason=payload.reason,
            estimated_regret=payload.estimated_regret,
            switching_cost=payload.switching_cost,
            conditions=[ConditionRecord(**condition.model_dump()) for condition in payload.conditions],
        )
        session.add(decision)
        session.commit()
        session.refresh(decision)
        return decision

    @application.get("/decisions", response_model=list[DecisionOutput])
    def list_decisions(session: SessionDependency) -> list[DecisionRecord]:
        """List recorded procurement decisions and their conditions."""
        return list(session.scalars(select(DecisionRecord).order_by(DecisionRecord.created_at.desc())))

    @application.post("/decisions/{decision_id}/dependencies", status_code=status.HTTP_201_CREATED)
    def add_dependency(
        decision_id: str, payload: DecisionLinkInput, session: SessionDependency
    ) -> dict[str, str]:
        """Record a directed dependency between two existing decisions."""
        if decision_id == payload.target_decision_id:
            raise HTTPException(status_code=422, detail="A decision cannot depend on itself")
        if session.get(DecisionRecord, decision_id) is None:
            raise HTTPException(status_code=404, detail="Source decision not found")
        if session.get(DecisionRecord, payload.target_decision_id) is None:
            raise HTTPException(status_code=404, detail="Target decision not found")
        link = DecisionLinkRecord(
            source_decision_id=decision_id,
            target_decision_id=payload.target_decision_id,
            relationship=payload.relationship,
        )
        session.add(link)
        session.commit()
        return {
            "id": link.id,
            "source_decision_id": decision_id,
            "target_decision_id": payload.target_decision_id,
        }

    @application.get("/decisions/{decision_id}/dependencies", response_model=list[str])
    def list_transitive_dependencies(decision_id: str, session: SessionDependency) -> list[str]:
        """Traverse transitive decision dependencies using a recursive SQL CTE."""
        if session.get(DecisionRecord, decision_id) is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        dependency_tree = (
            select(DecisionLinkRecord.target_decision_id.label("decision_id"))
            .where(DecisionLinkRecord.source_decision_id == decision_id)
            .cte("decision_dependency_tree", recursive=True)
        )
        recursive_links = select(DecisionLinkRecord.target_decision_id.label("decision_id")).join(
            dependency_tree,
            DecisionLinkRecord.source_decision_id == dependency_tree.c.decision_id,
        )
        dependency_tree = dependency_tree.union(recursive_links)
        query = select(dependency_tree.c.decision_id).where(dependency_tree.c.decision_id != decision_id)
        return list(session.scalars(query).unique())

    @application.post("/decisions/extract", response_model=ExtractionOutput)
    def extract_conditions(payload: ExtractionInput) -> ExtractionOutput:
        """Extract candidate conditions from text without assigning a score."""
        content = LLMClient().complete(
            "extraction",
            "Extract checkable supply-chain conditions from the reason. Return JSON as "
            '{"conditions":[{"entity":"...","field":"...","operator":"==|!=|<|<=|>|>=",'
            '"expected_value":...}]}. Use only supported operators and do not invent missing facts.',
            payload.reason,
        )
        try:
            return ExtractionOutput.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="LLM returned invalid condition JSON") from exc

    @application.post("/events/recheck", response_model=list[DecisionReviewOutput])
    def recheck_after_event(
        payload: StateChangeInput,
        session: SessionDependency,
        erp_connector: Annotated[ERPConnector, Depends(get_connector)],
    ) -> list[DecisionReviewOutput]:
        """Ingest a state event via the connector and recheck stored decisions."""
        previous_value = erp_connector.get_current_value(payload.entity, payload.field)
        erp_connector.ingest_event(payload.entity, payload.field, payload.new_value)
        session.add(StateEventRecord(
            entity=payload.entity,
            field=payload.field,
            old_value=previous_value,
            new_value=payload.new_value,
            event_time=payload.event_time,
        ))
        decisions = list(session.scalars(select(DecisionRecord)).unique())
        reviews = [persist_review(session, decision, erp_connector) for decision in decisions]
        session.commit()
        return reviews

    @application.post("/decisions/{decision_id}/explanation", response_model=ExplanationOutput)
    def explain_decision(
        decision_id: str,
        session: SessionDependency,
        erp_connector: Annotated[ERPConnector, Depends(get_connector)],
    ) -> ExplanationOutput:
        """Use the configured LLM only to phrase a deterministic review."""
        decision = session.get(DecisionRecord, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        review = persist_review(session, decision, erp_connector)
        session.commit()
        explanation = LLMClient().complete(
            "explanation",
            "Explain this deterministic procurement review in plain language. Do not change its result.",
            json.dumps({"decision": decision.reason, "review": review.model_dump()}),
        )
        return ExplanationOutput(explanation=explanation)

    return application


app = create_app()