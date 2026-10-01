import { useAsOf } from "../AsOfContext";
import { api } from "../api";
import { Empty, ErrorBanner, Loading, PageHeader, Stat } from "../components/ui";
import { pct } from "../format";
import { useAsync } from "../hooks";

export default function Metrics() {
  const { asOf, ready } = useAsOf();
  const { data, error, loading } = useAsync(() => api.metrics(asOf), [asOf], ready);

  const weeks = data ? Object.entries(data.flags_per_week).sort(([a], [b]) => a.localeCompare(b)) : [];
  const max = Math.max(1, ...weeks.map(([, count]) => count));

  return (
    <>
      <PageHeader title="Metrics" subtitle="How the review workflow is performing as of the simulated date." />
      {(!ready || loading) && <Loading />}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {data && ready && !loading && (
        <>
          <div className="stat-row">
            <Stat label="Action rate" value={pct(data.action_rate)} hint="Flags a planner acted on" />
            <Stat label="Extraction correction rate" value={pct(data.extraction_correction_rate)} hint="Proposals edited or rejected" />
            <Stat label="Weeks with flags" value={weeks.length} />
          </div>
          <section className="card">
            <h2>Flags per week</h2>
            {weeks.length === 0 ? (
              <Empty title="No flagged violations recorded yet." />
            ) : (
              <div className="bars" role="img" aria-label="Flags per week">
                {weeks.map(([week, count]) => (
                  <div className="bar" key={week} title={`${week}: ${count}`}>
                    <span className="bar-count">{count}</span>
                    <span className="bar-fill" style={{ height: `${(count / max) * 100}%` }} />
                    <span className="bar-label">{week}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
