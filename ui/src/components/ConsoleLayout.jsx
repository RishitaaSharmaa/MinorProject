import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { useWorkspace } from "../WorkspaceContext";
import { useAsOf } from "../AsOfContext";
import { DATASET_END, DATASET_START, TOTAL_DAYS, dayOffset, formatDate, fromOffset } from "../format";
import { agent } from "../api";
import { clearLocalData, engineStatus } from "../local/engine";
import ErrorBoundary from "./ErrorBoundary";
import Logo from "./Logo";

const NAV = [
  { to: "connect", label: "Connect data" },
  { to: "brief", label: "Morning Brief" },
  { to: "assumptions", label: "Confirm Assumptions" },
  { to: "decisions", label: "Decision Detail" },
  { to: "freshness", label: "Data Freshness" },
  { to: "metrics", label: "Metrics" },
  { to: "account", label: "Account & billing" },
];

// Typed dates can fall outside the dataset's simulated calendar; clamp them back in.
const clamp = (iso) => (iso < DATASET_START ? DATASET_START : iso > DATASET_END ? DATASET_END : iso);

function LocalNotice() {
  const [status, setStatus] = useState(engineStatus.get());
  useEffect(() => engineStatus.subscribe(setStatus), []);

  async function wipe() {
    if (!window.confirm("Delete everything stored in this browser? This cannot be undone.")) return;
    await clearLocalData();
    agent.disconnect();
    window.location.assign("/agent");
  }

  return (
    <div className="banner" role="status">
      {status ? `${status} (first start only)` : "Your data is stored in this browser only and is never uploaded."}{" "}
      <button className="btn btn-ghost btn-sm" onClick={wipe}>Delete local data</button>
    </div>
  );
}

export default function ConsoleLayout() {
  const { pathname } = useLocation();
  const { asOf, setAsOf, ready, recheckError, lastRecheck, recheckNow } = useAsOf();
  const { workspace, signedIn, hasAgent, leave } = useWorkspace();
  const tenant = workspace.tenant;

  const needsAgent = signedIn && !hasAgent && !pathname.endsWith("/account");

  if (workspace.auth_required && !signedIn) return <Navigate to="/login" state={{ from: pathname }} replace />;

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
        <div className="sidebar-account">
          {signedIn ? (
            <>
              <strong>{tenant.name}</strong>
              <span>{tenant.trial_expired ? "Trial ended" : `Free trial · ${tenant.trial_days_left} day${tenant.trial_days_left === 1 ? "" : "s"} left`}</span>
              <button className="btn btn-ghost btn-sm" onClick={leave}>Sign out</button>
            </>
          ) : (
            <>
              <strong>Demo workspace</strong>
              <span>Synthetic data, shared by everyone</span>
              <Link to="/signup" className="btn btn-primary btn-sm">Use your own data</Link>
            </>
          )}
        </div>
        <Link to="/" className="sidebar-link sidebar-back">← Back to overview</Link>
      </aside>

      <div className="console-main">
        <div className="topbar">
          {signedIn ? (
            <div className="topbar-date"><label>Data</label><strong>Live · {formatDate(asOf)}</strong></div>
          ) : (
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
          )}
          {!signedIn && <span className="topbar-range">Dataset covers {formatDate(DATASET_START)} – {formatDate(DATASET_END)}</span>}
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
        {signedIn && agent.connection?.local && <LocalNotice />}
        {signedIn && tenant.trial_expired && (
          <div className="banner banner-danger" role="alert">Your free trial has ended. Contact us to continue.</div>
        )}
        {recheckError && !(signedIn && tenant.trial_expired) && <div className="banner banner-danger" role="alert">{recheckError}</div>}
        <div className="console-content">
          <ErrorBoundary resetKey={pathname}>
            {needsAgent ? (
              <div className="card">
                <h2>Connect your agent to see your data</h2>
                <p className="muted">
                  Your data is never stored on this site. Run the DecisionWatch agent in your own network and
                  connect it; everything you see here is then read straight from it.
                </p>
                <Link to="/agent" className="btn btn-primary">Connect your agent</Link>
              </div>
            ) : <Outlet />}
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
