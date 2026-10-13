import { useState } from "react";
import { Link } from "react-router-dom";
import { useAsOf } from "../AsOfContext";
import { api } from "../api";
import { Empty, ErrorBanner, Loading, PageHeader, Stat } from "../components/ui";
import { formatDate } from "../format";
import { useAsync } from "../hooks";

const THRESHOLDS = [7, 14, 30, 60];

// Several assumptions (across decisions) usually watch the same ERP field, so
// group them by feed: one row per entity/field that went quiet.
function groupByFeed(rows) {
  const feeds = new Map();
  rows.forEach((row) => {
    const key = `${row.entity}|${row.field}`;
    const feed = feeds.get(key) ?? {
      key, entity: row.entity, field: row.field, lastEvent: row.last_event_time, ageDays: row.age_days,
      assumptions: 0, decisions: new Set(),
    };
    feed.assumptions += 1;
    feed.decisions.add(row.decision_id);
    feeds.set(key, feed);
  });
  return [...feeds.values()].sort((a, b) => b.ageDays - a.ageDays);
}

function FeedTable({ feeds, showLast }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>ERP field</th>
          {showLast && <th>Last update</th>}
          {showLast && <th>Silent for</th>}
          <th>Assumptions</th>
          <th>Decisions</th>
        </tr>
      </thead>
      <tbody>
        {feeds.map((feed) => (
          <tr key={feed.key}>
            <td><strong>{feed.entity}</strong> <span className="muted">· {feed.field}</span></td>
            {showLast && <td>{formatDate(feed.lastEvent)}</td>}
            {showLast && <td><span className="pill pill-warn">{Math.round(feed.ageDays)} days</span></td>}
            <td>{feed.assumptions}</td>
            <td>
              {[...feed.decisions].sort().slice(0, 4).map((id) => (
                <Link key={id} to={`/console/decisions/${id}`} className="muted" style={{ marginRight: 8 }}>{id}</Link>
              ))}
              {feed.decisions.size > 4 && <span className="muted">+{feed.decisions.size - 4} more</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Freshness() {
  const { asOf, ready } = useAsOf();
  const [days, setDays] = useState(14);
  const { data, error, loading } = useAsync(() => api.staleness(asOf, days), [asOf, days], ready);

  const silent = data ? groupByFeed(data.stale) : [];
  const never = data ? groupByFeed(data.never_reported) : [];

  return (
    <>
      <PageHeader
        title="Data Freshness"
        subtitle="Assumptions stay “live” only because nothing has contradicted them. When an ERP feed goes quiet, they are unverified, not confirmed."
      >
        <div className="controls">
          <label>
            Stale after
            <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
              {THRESHOLDS.map((n) => <option key={n} value={n}>{n} days</option>)}
            </select>
          </label>
        </div>
      </PageHeader>

      {(!ready || loading) && <Loading />}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {data && ready && !loading && (
        <>
          <div className="stat-row">
            <Stat label="Silent ERP feeds" value={silent.length} tone={silent.length ? "warn" : "ok"} hint="Reported before, then went quiet" />
            <Stat label="Unverified assumptions" value={data.stale_count} tone={data.stale_count ? "warn" : "ok"} />
            <Stat label="Decisions affected" value={data.decisions_affected.length} />
            <Stat label="Never reported" value={data.never_reported_count} hint="No event ever seen on the field" />
          </div>

          <section className="card">
            <h2>Silent feeds</h2>
            {silent.length === 0 ? (
              <Empty title="Every watched feed has reported recently." />
            ) : (
              <FeedTable feeds={silent} showLast />
            )}
          </section>

          {never.length > 0 && (
            <section className="card">
              <h2>Never reported</h2>
              <p className="muted">
                These fields have no event on record, so their assumptions have never been re-checked against fresh data.
              </p>
              <FeedTable feeds={never} showLast={false} />
            </section>
          )}
        </>
      )}
    </>
  );
}
