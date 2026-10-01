import { useState } from "react";
import { Link } from "react-router-dom";
import { useAsOf } from "../AsOfContext";
import { api } from "../api";
import SuggestionPanel from "../components/SuggestionPanel";
import { ConfidenceBadge, Empty, ErrorBanner, Loading, PageHeader, Stat } from "../components/ui";
import { inr } from "../format";
import { useAsync } from "../hooks";

const ACTIONS = ["keep", "reduce", "delay", "cancel"];

export default function Brief() {
  const { asOf, ready } = useAsOf();
  const [limit, setLimit] = useState(10);
  const { data, error, loading, reload } = useAsync(
    () => api.brief(asOf, limit, true),
    [asOf, limit],
    ready,
  );

  return (
    <>
      <PageHeader
        title="Morning Brief"
        subtitle="Decisions whose confirmed assumptions have broken and where acting now is worth more than keeping the order."
      >
        <div className="controls">
          <label>
            Decisions to show
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
              {[5, 10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
      </PageHeader>

      {(!ready || loading) && <Loading label={ready ? "Building brief and explanations…" : "Replaying events…"} />}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {data && ready && !loading && (
        <>
          <div className="stat-row">
            <Stat label="Needs action" value={data.cards.length} tone={data.cards.length ? "warn" : "ok"} />
            <Stat label="Reviewed and kept" value={data.reviewed_and_kept} hint="Broken, but fee ≥ savings" />
          </div>
          {data.cards.length === 0 && (
            <Empty title="Nothing worth acting on today.">
              If this is unexpected, confirm assumptions for some decisions first. The brief only covers confirmed assumptions.
            </Empty>
          )}
          {data.cards.map((card) => (
            <BriefCard key={card.score.decision_id} card={card} asOf={asOf} onActed={reload} />
          ))}
        </>
      )}
    </>
  );
}

function BriefCard({ card, asOf, onActed }) {
  const { score, explanation } = card;
  const used = score.assumptions_used;
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const sibling = score.switching_cost_breakdown.sibling_impact;

  async function act(action, noteText = note) {
    setBusy(true);
    setStatus(null);
    try {
      await api.act(score.decision_id, action, noteText);
      onActed();
    } catch (error) {
      setStatus({ tone: "danger", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card brief-card">
      <div className="brief-top">
        <div>
          <h2>
            <Link to={`/console/decisions/${score.decision_id}`}>{score.decision_id}</Link>
            <span className={`rec rec-${score.recommendation}`}>{score.recommendation}</span>
          </h2>
          <p className="muted">
            Broken reason: {used.normalized_type} on {used.entity} ({used.field} {used.operator} {String(used.expected_value)})
          </p>
        </div>
        <div className="brief-metrics">
          <Stat label="Net benefit" value={inr(score.net_benefit)} tone="ok" />
          <Stat
            label="Deadline"
            value={score.days_to_window === null ? "No limit" : `${score.days_to_window} days`}
            tone={score.days_to_window !== null && score.days_to_window <= 3 ? "danger" : undefined}
          />
          <div className="stat"><span className="stat-label">Confidence</span><ConfidenceBadge level={score.confidence} /></div>
        </div>
      </div>

      <section className="reasoning">
        <h3>Why this decision</h3>
        <ul>{(score.reasoning ?? []).map((line) => <li key={line}>{line}</li>)}</ul>
      </section>
      {explanation && <p className="explanation">{explanation}</p>}

      <SuggestionPanel
        decisionId={score.decision_id}
        asOf={asOf}
        onApply={(action, headline) => act(action, note || `AI suggestion: ${headline}`)}
      />

      {sibling > 0 && (
        <div className="banner banner-warn">Sibling impact: acting forfeits {inr(sibling)} in linked-order savings.</div>
      )}

      <details className="breakdown">
        <summary>Arithmetic breakdown</summary>
        <dl className="kv">
          <dt>Order value</dt><dd>{inr(score.order_value)}</dd>
          <dt>Cost of keeping</dt><dd>{inr(score.cost_keep)}</dd>
          <dt>Best alternative</dt><dd>{score.best_alternative}</dd>
          <dt>Regret</dt><dd>{inr(score.regret)}</dd>
          <dt>Switching cost</dt><dd>{inr(score.switching_cost)}</dd>
          <dt>Net benefit</dt><dd>{inr(score.net_benefit)}</dd>
        </dl>
        <table className="table">
          <thead>
            <tr><th>Action</th><th>Residual</th><th>Fee</th><th>In transit</th><th>Sibling</th><th>Switching</th><th>Total</th></tr>
          </thead>
          <tbody>
            {Object.entries(score.actions).map(([name, cost]) => (
              <tr key={name} className={name === score.best_alternative ? "row-best" : undefined}>
                <td>{name}</td>
                <td>{inr(cost.residual_cost)}</td>
                <td>{inr(cost.fee)}</td>
                <td>{inr(cost.in_transit)}</td>
                <td>{inr(cost.sibling_impact)}</td>
                <td>{inr(cost.switching_cost)}</td>
                <td>{inr(cost.total_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="raw">
          <summary>Cost-of-keeping detail</summary>
          <pre>{JSON.stringify(score.cost_keep_breakdown, null, 2)}</pre>
        </details>
      </details>

      <div className="action-bar">
        <input
          type="text"
          placeholder="Add a note (optional)"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          aria-label={`Note for ${score.decision_id}`}
        />
        <div className="btn-group">
          {ACTIONS.map((action) => (
            <button
              key={action}
              className={`btn btn-sm ${action === score.recommendation ? "btn-primary" : "btn-outline"}`}
              disabled={busy}
              onClick={() => act(action)}
            >
              {action[0].toUpperCase() + action.slice(1)}
            </button>
          ))}
        </div>
      </div>
      {status && <ErrorBanner>{status.text}</ErrorBanner>}
    </article>
  );
}
