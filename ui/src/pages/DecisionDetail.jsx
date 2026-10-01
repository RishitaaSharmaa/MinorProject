import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAsOf } from "../AsOfContext";
import { api } from "../api";
import SuggestionPanel from "../components/SuggestionPanel";
import { Empty, ErrorBanner, Loading, PageHeader, Stat, StatusBadge } from "../components/ui";
import { formatDate, inr } from "../format";
import { useAsync } from "../hooks";

const show = (value) => (value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value));

export default function DecisionDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { asOf, ready } = useAsOf();
  const [input, setInput] = useState(id ?? "");
  useEffect(() => setInput(id ?? ""), [id]);

  const { data, error, loading } = useAsync(() => api.decision(id, asOf), [id, asOf], ready && Boolean(id));

  return (
    <>
      <PageHeader title="Decision Detail" subtitle="Facts, assumptions and the state changes affecting one decision." />
      <form
        className="card inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (input.trim()) navigate(`/console/decisions/${encodeURIComponent(input.trim())}`);
        }}
      >
        <label>
          Decision ID
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="e.g. D-00123" />
        </label>
        <button className="btn btn-primary" disabled={!input.trim()}>Load decision</button>
      </form>

      {!id && <Empty title="Enter a decision ID to see its history." />}
      {id && (!ready || loading) && <Loading />}
      {id && error && <ErrorBanner>{error}</ErrorBanner>}
      {data && ready && !loading && <Detail detail={data} asOf={asOf} />}
    </>
  );
}

function Detail({ detail, asOf }) {
  return (
    <>
      <div className="stat-row">
        <Stat label="Status" value={detail.status} />
        <Stat label="Type" value={detail.decision_type} />
        <Stat label="Quantity" value={show(detail.quantity)} />
        <Stat label="Unit price" value={inr(detail.unit_price)} />
        <Stat label="Override" value={detail.is_override ? "Yes" : "No"} />
      </div>

      <section className="card">
        <h2>Recorded reason</h2>
        <p>{detail.free_text_reason || <span className="muted">No recorded reason.</span>}</p>
        <dl className="kv">
          <dt>Item</dt><dd>{show(detail.item_id)}</dd>
          <dt>Supplier</dt><dd>{show(detail.supplier_id)}</dd>
          <dt>PO date</dt><dd>{detail.po_date ? formatDate(detail.po_date) : "—"}</dd>
          <dt>Expected delivery</dt><dd>{detail.expected_delivery ? formatDate(detail.expected_delivery) : "—"}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Assumptions</h2>
        {detail.assumptions.length === 0 ? (
          <p className="muted">No assumptions recorded for this decision.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Condition</th><th>Source</th><th>Status</th><th>Confirmed</th></tr></thead>
            <tbody>
              {detail.assumptions.map((assumption) => (
                <tr key={assumption.id}>
                  <td><code>{assumption.condition.type} · {assumption.condition.entity_ref} {assumption.condition.op} {show(assumption.condition.value)}</code></td>
                  <td>{assumption.source}</td>
                  <td><StatusBadge status={assumption.status} /></td>
                  <td>{assumption.confirmed_by_user ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Timeline</h2>
        {detail.timeline.length === 0 ? (
          <p className="muted">No recorded state changes for this decision's item or supplier.</p>
        ) : (
          <table className="table">
            <thead><tr><th>When</th><th>Entity</th><th>Field</th><th>From</th><th>To</th></tr></thead>
            <tbody>
              {detail.timeline.map((event) => (
                <tr key={event.id}>
                  <td>{formatDate(event.event_time)}</td>
                  <td>{event.entity_type}:{event.entity_id}</td>
                  <td>{event.field}</td>
                  <td>{show(event.old_value)}</td>
                  <td>{show(event.new_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {detail.score && (
        <section className="card">
          <h2>Current score</h2>
          <div className="stat-row">
            <Stat label="Recommendation" value={detail.score.recommendation} />
            <Stat label="Regret" value={inr(detail.score.regret)} />
            <Stat label="Switching cost" value={inr(detail.score.switching_cost)} />
            <Stat label="Net benefit" value={inr(detail.score.net_benefit)} tone={detail.score.flagged ? "warn" : undefined} />
          </div>
          <section className="reasoning">
            <h3>Why this decision</h3>
            <ul>{(detail.score.reasoning ?? []).map((line) => <li key={line}>{line}</li>)}</ul>
          </section>
          <SuggestionPanel decisionId={detail.id} asOf={asOf} />
          <details className="raw">
            <summary>Full scoring detail</summary>
            <pre>{JSON.stringify(detail.score, null, 2)}</pre>
          </details>
        </section>
      )}
    </>
  );
}
