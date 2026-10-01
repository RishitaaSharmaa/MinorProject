"""Streamlit console for the DecisionWatch morning brief and review workflow.

Talks only to the backend API (never the database directly), so it can run
against any deployment that exposes ``/brief``, ``/decisions/{id}``,
``/decisions/{id}/action``, and ``/metrics``.
"""

from datetime import date
from typing import Any

import requests
import streamlit as st

DEFAULT_API_URL = "http://localhost:8000"
#: Matches the synthetic dataset's simulated calendar (see data_generator/config.py).
DATASET_START = date(2025, 4, 1)
DATASET_END = date(2025, 9, 30)
CONFIDENCE_BADGES = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}
ACTIONS = ("keep", "reduce", "delay", "cancel")


def _api_url() -> str:
    """Return the configured backend base URL for this session."""
    return st.session_state.get("api_url", DEFAULT_API_URL)


def _get(path: str, **params: Any) -> Any:
    """Send one GET request to the backend API and return its JSON body."""
    response = requests.get(f"{_api_url()}{path}", params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: dict[str, Any] | None = None, **params: Any) -> Any:
    """Send one POST request to the backend API and return its JSON body."""
    response = requests.post(f"{_api_url()}{path}", json=payload, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _inr(value: float | None) -> str:
    """Format a number as a rounded INR amount."""
    return "—" if value is None else f"₹{value:,.0f}"


def _parse_value(value_text: str) -> object:
    """Parse a UI condition value as boolean, number, or text."""
    normalized = value_text.strip()
    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"
    try:
        return int(normalized)
    except ValueError:
        try:
            return float(normalized)
        except ValueError:
            return normalized


def _sidebar_as_of() -> date:
    """Render the sidebar and return the currently simulated date."""
    st.sidebar.title("DecisionWatch")
    st.session_state.setdefault("api_url", DEFAULT_API_URL)
    st.sidebar.text_input("API URL", key="api_url")
    st.session_state.setdefault("as_of", DATASET_END)
    as_of = st.sidebar.slider(
        "Simulated date",
        min_value=DATASET_START,
        max_value=DATASET_END,
        value=st.session_state["as_of"],
    )
    st.session_state["as_of"] = as_of

    # Confirming an assumption never changes its status by itself -- only a
    # recheck pass detects that a later event broke it. Rerun it whenever the
    # simulated date changes, so the brief always reflects that date.
    if st.session_state.get("last_rechecked_as_of") != as_of:
        try:
            _post("/events/recheck", as_of=as_of.isoformat())
        except requests.RequestException as exc:
            st.sidebar.error(f"Recheck failed: {exc}")
        else:
            st.session_state["last_rechecked_as_of"] = as_of

    st.sidebar.caption(f"Acting as of {as_of.isoformat()}")
    if st.sidebar.button("Recheck now"):
        try:
            _post("/events/recheck", as_of=as_of.isoformat())
        except requests.RequestException as exc:
            st.sidebar.error(f"Recheck failed: {exc}")
        else:
            st.sidebar.success("Rechecked.")
    return as_of


def page_morning_brief(as_of: date) -> None:
    """Render the ranked action brief with arithmetic breakdowns and action buttons."""
    st.header("Morning Brief")
    controls = st.columns([1, 1, 2])
    limit = controls[0].slider("Cards to show", min_value=1, max_value=25, value=10)
    explain = controls[1].checkbox("LLM explanations", value=False)

    try:
        brief = _get("/brief", as_of=as_of.isoformat(), limit=limit, explain=explain)
    except requests.RequestException as exc:
        st.error(f"Could not reach the DecisionWatch API: {exc}")
        return

    if not brief["cards"]:
        st.success("Nothing worth acting on today.")

    for card in brief["cards"]:
        _render_brief_card(card)

    with st.expander(f"Reviewed and kept: {brief['reviewed_and_kept']}", expanded=False):
        st.caption("Checked, and the broken assumption did not clear the flag bar (fee ≥ savings).")


def _render_brief_card(card: dict[str, Any]) -> None:
    """Render one flagged decision as an actionable card."""
    score = card["score"]
    assumptions = score["assumptions_used"]
    with st.container(border=True):
        top = st.columns([2, 1, 1, 1])
        top[0].subheader(f"{score['decision_id']} — {score['recommendation'].upper()}")
        top[1].metric("Net benefit", _inr(score["net_benefit"]))
        top[2].markdown(f"**Confidence**\n\n{CONFIDENCE_BADGES.get(score['confidence'], score['confidence'])}")
        deadline = score["days_to_window"]
        top[3].markdown(f"**Deadline**\n\n{deadline} days" if deadline is not None else "**Deadline**\n\nno limit")

        st.caption(
            f"Broken reason: {assumptions['normalized_type']} on {assumptions['entity']} "
            f"({assumptions['field']} {assumptions['operator']} {assumptions['expected_value']})"
        )
        if card["explanation"]:
            st.write(card["explanation"])
        if score["confidence_reasons"]:
            st.caption("Confidence downgraded because: " + "; ".join(score["confidence_reasons"]))

        sibling_impact = score["switching_cost_breakdown"]["sibling_impact"]
        if sibling_impact:
            st.warning(f"Sibling impact: acting forfeits {_inr(sibling_impact)} in linked-order savings.")

        with st.expander("Arithmetic breakdown"):
            st.json({
                "order_value": score["order_value"],
                "cost_keep": score["cost_keep"],
                "cost_keep_breakdown": score["cost_keep_breakdown"],
                "best_alternative": score["best_alternative"],
                "actions": score["actions"],
                "regret": score["regret"],
                "switching_cost": score["switching_cost"],
                "switching_cost_breakdown": score["switching_cost_breakdown"],
                "net_benefit": score["net_benefit"],
            })

        note = st.text_input("Note", key=f"note-{score['decision_id']}")
        action_columns = st.columns(len(ACTIONS))
        for column, action in zip(action_columns, ACTIONS):
            if column.button(action.capitalize(), key=f"{action}-{score['decision_id']}"):
                try:
                    _post(f"/decisions/{score['decision_id']}/action", {"action": action, "note": note})
                except requests.RequestException as exc:
                    st.error(f"Could not record the action: {exc}")
                else:
                    st.success(f"Recorded {action} for {score['decision_id']}.")
                    st.rerun()


def page_confirm_assumptions() -> None:
    """Render editable, LLM-proposed conditions with a one-click confirm/reject."""
    st.header("Confirm Assumptions")
    decision_id = st.text_input("Decision ID")
    if st.button("Extract proposals") and decision_id:
        try:
            proposals = _post(f"/decisions/{decision_id}/extract")
        except requests.RequestException as exc:
            st.error(f"Extraction failed: {exc}")
        else:
            st.session_state["proposals"] = proposals
            st.session_state["proposal_decision_id"] = decision_id

    proposals = st.session_state.get("proposals", [])
    if not decision_id or st.session_state.get("proposal_decision_id") != decision_id:
        return
    if not proposals:
        st.info("No proposals extracted yet.")
        return

    operators = ["==", "!=", "<", "<=", ">", ">="]
    for proposal in proposals:
        _render_proposal_row(decision_id, proposal, operators)


def _render_proposal_row(decision_id: str, proposal: dict[str, Any], operators: list[str]) -> None:
    """Render one editable extraction proposal with confirm and reject actions."""
    key = proposal["proposal_id"]
    with st.container(border=True):
        st.caption(f"{proposal['source']} · confidence {proposal['confidence']:.2f}")
        for warning in proposal.get("warnings", []):
            st.warning(warning)

        columns = st.columns([2, 2, 1, 2])
        condition_type = columns[0].text_input("Type", value=proposal["type"], key=f"type-{key}")
        entity_ref = columns[1].text_input("Entity", value=proposal["entity_ref"], key=f"entity-{key}")
        operator = columns[2].selectbox("Op", operators, index=operators.index(proposal["op"]), key=f"op-{key}")
        value_text = columns[3].text_input("Value", value=str(proposal["value"]), key=f"value-{key}")

        actions = st.columns(2)
        if actions[0].button("Confirm", key=f"confirm-{key}"):
            try:
                _post(f"/decisions/{decision_id}/assumptions/confirm", {
                    "accepted": [{
                        "proposal_id": key,
                        "condition": {
                            "type": condition_type,
                            "entity_ref": entity_ref,
                            "op": operator,
                            "value": _parse_value(value_text),
                            "needs_value_from_planner": proposal.get("needs_value_from_planner", False),
                        },
                    }],
                    "rejected_proposal_ids": [],
                })
            except requests.RequestException as exc:
                st.error(f"Could not confirm: {exc}")
            else:
                st.success("Confirmed.")
        if actions[1].button("Reject", key=f"reject-{key}"):
            try:
                _post(f"/decisions/{decision_id}/assumptions/confirm", {
                    "accepted": [], "rejected_proposal_ids": [key],
                })
            except requests.RequestException as exc:
                st.error(f"Could not reject: {exc}")
            else:
                st.info("Rejected.")


def page_decision_detail(as_of: date) -> None:
    """Render one decision's facts, assumptions, and state-change timeline."""
    st.header("Decision Detail")
    decision_id = st.text_input("Decision ID", key="detail_decision_id")
    if not decision_id:
        return
    try:
        detail = _get(f"/decisions/{decision_id}", as_of=as_of.isoformat())
    except requests.RequestException as exc:
        st.error(f"Could not load decision: {exc}")
        return

    columns = st.columns(4)
    columns[0].metric("Status", detail["status"])
    columns[1].metric("Quantity", detail["quantity"] if detail["quantity"] is not None else "—")
    columns[2].metric("Unit price", _inr(detail["unit_price"]))
    columns[3].metric("Override", "Yes" if detail["is_override"] else "No")
    st.write(detail["free_text_reason"] or "_No recorded reason._")

    st.subheader("Assumptions")
    for assumption in detail["assumptions"]:
        st.write(f"[{assumption['status']}] {assumption['condition']} (source: {assumption['source']})")
    if not detail["assumptions"]:
        st.caption("No assumptions recorded for this decision.")

    st.subheader("Timeline")
    if detail["timeline"]:
        st.dataframe(
            [
                {
                    "When": event["event_time"],
                    "Entity": f"{event['entity_type']}:{event['entity_id']}",
                    "Field": event["field"],
                    "From": event["old_value"],
                    "To": event["new_value"],
                }
                for event in detail["timeline"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No recorded state changes for this decision's item or supplier.")

    if detail["score"] is not None:
        with st.expander("Current score"):
            st.json(detail["score"])


def page_metrics(as_of: date) -> None:
    """Render operational metrics: flags/week, action rate, correction rate."""
    st.header("Metrics")
    try:
        metrics = _get("/metrics", as_of=as_of.isoformat())
    except requests.RequestException as exc:
        st.error(f"Could not load metrics: {exc}")
        return

    columns = st.columns(2)
    columns[0].metric("Action rate", f"{metrics['action_rate'] * 100:.0f}%")
    columns[1].metric("Extraction correction rate", f"{metrics['extraction_correction_rate'] * 100:.0f}%")

    st.subheader("Flags per week")
    if metrics["flags_per_week"]:
        st.bar_chart(metrics["flags_per_week"])
    else:
        st.caption("No flagged violations recorded yet.")


def main() -> None:
    """Render the sidebar-driven, multi-page DecisionWatch console."""
    st.set_page_config(page_title="DecisionWatch", layout="wide")
    as_of = _sidebar_as_of()
    page = st.sidebar.radio("Page", ["Morning Brief", "Confirm Assumptions", "Decision Detail", "Metrics"])
    if page == "Morning Brief":
        page_morning_brief(as_of)
    elif page == "Confirm Assumptions":
        page_confirm_assumptions()
    elif page == "Decision Detail":
        page_decision_detail(as_of)
    else:
        page_metrics(as_of)


if __name__ == "__main__":
    main()
