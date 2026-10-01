import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBanner, Loading, PageHeader } from "../components/ui";
import { parseValue } from "../format";

const OPERATORS = ["==", "!=", "<", "<=", ">", ">="];

export default function Assumptions() {
  const [decisionId, setDecisionId] = useState("");
  const [loaded, setLoaded] = useState(null); // { decisionId, proposals }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function extract(event) {
    event.preventDefault();
    const id = decisionId.trim();
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      setLoaded({ decisionId: id, proposals: await api.extract(id) });
    } catch (err) {
      setLoaded(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Confirm Assumptions"
        subtitle="Review the conditions proposed from a decision's note and ERP context. Only confirmed assumptions are watched."
      />
      <form className="card inline-form" onSubmit={extract}>
        <label>
          Decision ID
          <input value={decisionId} onChange={(event) => setDecisionId(event.target.value)} placeholder="e.g. D-00123" />
        </label>
        <button className="btn btn-primary" disabled={loading || !decisionId.trim()}>Extract proposals</button>
      </form>

      {loading && <Loading label="Extracting assumptions…" />}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {loaded && !loading && loaded.proposals.length === 0 && (
        <Empty title="No proposals were extracted for this decision." />
      )}
      {loaded && !loading && loaded.proposals.map((proposal) => (
        <ProposalCard key={proposal.proposal_id} decisionId={loaded.decisionId} proposal={proposal} />
      ))}
    </>
  );
}

function ProposalCard({ decisionId, proposal }) {
  const [condition, setCondition] = useState({
    type: proposal.type,
    entity_ref: proposal.entity_ref,
    op: proposal.op,
    value: String(proposal.value),
  });
  const [outcome, setOutcome] = useState(null); // { tone, text }
  const [busy, setBusy] = useState(false);
  const set = (field) => (event) => setCondition({ ...condition, [field]: event.target.value });
  const settled = outcome?.tone === "ok";

  async function submit(kind) {
    setBusy(true);
    setOutcome(null);
    const payload = kind === "confirm"
      ? {
          accepted: [{
            proposal_id: proposal.proposal_id,
            condition: {
              type: condition.type,
              entity_ref: condition.entity_ref,
              op: condition.op,
              value: parseValue(condition.value),
              needs_value_from_planner: proposal.needs_value_from_planner ?? false,
            },
          }],
          rejected_proposal_ids: [],
        }
      : { accepted: [], rejected_proposal_ids: [proposal.proposal_id] };
    try {
      await api.confirm(decisionId, payload);
      setOutcome({ tone: "ok", text: kind === "confirm" ? "Confirmed. This assumption is now being watched." : "Rejected." });
    } catch (err) {
      setOutcome({ tone: "danger", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card">
      <div className="proposal-meta">
        <span className="pill pill-neutral">{proposal.source}</span>
        <span className="muted small">Confidence {Number(proposal.confidence).toFixed(2)}</span>
      </div>
      {(proposal.warnings ?? []).map((warning) => (
        <div className="banner banner-warn" key={warning}>{warning}</div>
      ))}
      <div className="form-grid">
        <label>Type<input value={condition.type} onChange={set("type")} disabled={settled} /></label>
        <label>Entity<input value={condition.entity_ref} onChange={set("entity_ref")} disabled={settled} /></label>
        <label>
          Operator
          <select value={condition.op} onChange={set("op")} disabled={settled}>
            {OPERATORS.map((op) => <option key={op}>{op}</option>)}
          </select>
        </label>
        <label>Value<input value={condition.value} onChange={set("value")} disabled={settled} /></label>
      </div>
      {proposal.needs_value_from_planner && !settled && (
        <p className="muted small">The planner needs to supply this value before confirming.</p>
      )}
      {!settled && (
        <div className="btn-group">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => submit("confirm")}>Confirm</button>
          <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => submit("reject")}>Reject</button>
        </div>
      )}
      {outcome && (outcome.tone === "ok"
        ? <div className="banner banner-ok">{outcome.text}</div>
        : <ErrorBanner>{outcome.text}</ErrorBanner>)}
    </article>
  );
}
