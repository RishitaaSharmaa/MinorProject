export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading…" }) {
  return <div className="loading" role="status"><span className="spinner" />{label}</div>;
}

export function ErrorBanner({ children }) {
  return <div className="banner banner-danger" role="alert">{children}</div>;
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

const CONFIDENCE_TONE = { high: "ok", medium: "warn", low: "danger" };
export function ConfidenceBadge({ level }) {
  return <span className={`pill pill-${CONFIDENCE_TONE[level] ?? "neutral"}`}>{level} confidence</span>;
}

export function StatusBadge({ status }) {
  const tone = { live: "ok", violated: "danger", retired: "neutral" }[status] ?? "neutral";
  return <span className={`pill pill-${tone}`}>{status}</span>;
}
