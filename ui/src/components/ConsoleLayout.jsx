import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAsOf } from "../AsOfContext";
import { DATASET_END, DATASET_START, TOTAL_DAYS, dayOffset, formatDate, fromOffset } from "../format";
import ErrorBoundary from "./ErrorBoundary";
import Logo from "./Logo";

const NAV = [
  { to: "brief", label: "Morning Brief" },
  { to: "assumptions", label: "Confirm Assumptions" },
  { to: "decisions", label: "Decision Detail" },
  { to: "metrics", label: "Metrics" },
];

// Typed dates can fall outside the dataset's simulated calendar; clamp them back in.
const clamp = (iso) => (iso < DATASET_START ? DATASET_START : iso > DATASET_END ? DATASET_END : iso);

export default function ConsoleLayout() {
  const { pathname } = useLocation();
  const { asOf, setAsOf, ready, recheckError, lastRecheck, recheckNow } = useAsOf();

  return (
    <div className="console">
      <aside className="sidebar">
        <Link to="/" className="sidebar-brand"><Logo light /></Link>
        <nav aria-label="Console">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <Link to="/" className="sidebar-link sidebar-back">← Back to overview</Link>
      </aside>

      <div className="console-main">
        <div className="topbar">
          <div className="topbar-date">
            <label htmlFor="as-of">Simulated date</label>
            <div className="date-picker">
              <button
                className="btn btn-ghost btn-sm"
                aria-label="Previous day"
                disabled={dayOffset(asOf) <= 0}
                onClick={() => setAsOf(fromOffset(dayOffset(asOf) - 1))}
              >‹</button>
              <input
                id="as-of"
                type="date"
                min={DATASET_START}
                max={DATASET_END}
                value={asOf}
                onChange={(event) => event.target.value && setAsOf(clamp(event.target.value))}
              />
              <button
                className="btn btn-ghost btn-sm"
                aria-label="Next day"
                disabled={dayOffset(asOf) >= TOTAL_DAYS}
                onClick={() => setAsOf(fromOffset(dayOffset(asOf) + 1))}
              >›</button>
            </div>
          </div>
          <span className="topbar-range">Dataset covers {formatDate(DATASET_START)} – {formatDate(DATASET_END)}</span>
          <div className="topbar-status">
            {!ready ? (
              <span className="pill pill-neutral">Rechecking…</span>
            ) : recheckError ? (
              <span className="pill pill-danger" title={recheckError}>Recheck failed</span>
            ) : (
              <span className="pill pill-ok" title={`${lastRecheck?.events_processed ?? 0} events replayed`}>
                {lastRecheck?.violations ?? 0} violated · {lastRecheck?.assumptions_rechecked ?? 0} checked
              </span>
            )}
            <button className="btn btn-ghost btn-sm" onClick={recheckNow}>Recheck now</button>
          </div>
        </div>
        {recheckError && <div className="banner banner-danger" role="alert">{recheckError}</div>}
        <div className="console-content">
          <ErrorBoundary resetKey={pathname}><Outlet /></ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
