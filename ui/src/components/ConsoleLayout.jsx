import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAsOf } from "../AsOfContext";
import { DATASET_END, DATASET_START, TOTAL_DAYS, dayOffset, formatDate, fromOffset } from "../format";
import ErrorBoundary from "./ErrorBoundary";
import Logo from "./Logo";

const NAV = [
  { to: "brief", label: "Morning Brief", icon: "M4 5h16M4 10h16M4 15h10M4 20h7" },
  { to: "assumptions", label: "Confirm Assumptions", icon: "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9" },
  { to: "decisions", label: "Decision Detail", icon: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5" },
  { to: "freshness", label: "Data Freshness", icon: "M12 7v5l3 3M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" },
  { to: "metrics", label: "Metrics", icon: "M4 20V10M10 20V4M16 20v-7M22 20H2" },
];

function NavIcon({ d }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

// Typed dates can fall outside the dataset's simulated calendar; clamp them back in.
const clamp = (iso) => (iso < DATASET_START ? DATASET_START : iso > DATASET_END ? DATASET_END : iso);

export default function ConsoleLayout() {
  const { pathname } = useLocation();
  const { asOf, setAsOf, ready, recheckError, lastRecheck, recheckNow } = useAsOf();

  return (
    <div className="console">
      <aside className="sidebar">
        <Link to="/" className="sidebar-brand"><Logo light /></Link>
        <span className="sidebar-label">Workspace</span>
        <nav aria-label="Console">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `sidebar-link${isActive ? " active" : ""}`}>
              <NavIcon d={item.icon} />{item.label}
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
