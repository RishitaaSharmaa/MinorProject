import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { agent, api } from "../api";
import { Empty, ErrorBanner, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks";
import { useWorkspace } from "../WorkspaceContext";

const DATE_FORMATS = ["auto", "DD/MM/YYYY", "MM/DD/YYYY", "DD-MM-YYYY", "DD.MM.YYYY", "DD-Mon-YYYY", "YYYYMMDD"];
const MAX_BYTES = 14 * 1024 * 1024;

function ErpSync({ tick, onDone }) {
  const status = useAsync(() => api.syncStatus(), [tick]);
  const [state, setState] = useState({ busy: null, message: null, error: null, result: null });

  if (status.loading || status.error || !status.data?.configured) return null; // nothing to show without an ERP
  const { source, interval_minutes: interval, runs } = status.data;
  const label = { sap_b1: "SAP Business One", netsuite: "NetSuite" }[source] ?? source;
  const last = runs[0];

  async function run(kind) {
    setState({ busy: kind, message: null, error: null, result: null });
    try {
      if (kind === "test") {
        setState({ busy: null, message: (await api.syncTest()).message, error: null, result: null });
      } else {
        const result = await api.syncNow();
        setState({ busy: null, message: null, error: null, result });
        onDone();
      }
    } catch (error) {
      setState({ busy: null, message: null, error: error.message, result: null });
    }
  }

  return (
    <div className="card">
      <h2>Sync from {label}</h2>
      <p className="muted">
        Your agent reads {label} with a read-only account and loads suppliers, items, purchase orders and stock the same
        way a file import does. {interval > 0 ? `It also syncs automatically every ${interval} minutes.` : "Syncs run when you press the button."}
        {last && <> Last sync: {new Date(last.created_at).toLocaleString()}.</>}
      </p>
      <div className="wizard-actions">
        <button className="btn btn-outline" onClick={() => run("test")} disabled={state.busy}>
          {state.busy === "test" ? "Checking…" : "Test connection"}
        </button>
        <button className="btn btn-primary" onClick={() => run("sync")} disabled={state.busy}>
          {state.busy === "sync" ? "Syncing…" : "Sync now"}
        </button>
      </div>
      {state.message && <div className="banner banner-ok" role="status">{state.message}</div>}
      {state.error && <ErrorBanner>{state.error}</ErrorBanner>}
      {state.result && (
        <>
          <div className="banner banner-ok" role="status">
            Sync finished.
            {state.result.change_events ? ` ${state.result.change_events} supplier change(s) recorded.` : ""}
            {state.result.decisions_flagged ? ` ${state.result.decisions_flagged} decision(s) flagged.` : ""}
          </div>
          {state.result.warnings.map((w) => <div key={w} className="banner banner-warn">{w}</div>)}
          <table className="table">
            <thead><tr><th>Dataset</th><th>Read</th><th>Loaded</th><th>Skipped</th></tr></thead>
            <tbody>
              {state.result.datasets.map((d) => (
                <tr key={d.dataset}><td>{d.dataset}</td><td>{d.fetched}</td><td>{d.imported}</td><td>{d.rejected}</td></tr>
              ))}
            </tbody>
          </table>
          {state.result.datasets.flatMap((d) => d.errors.slice(0, 3).map((e) => `${d.dataset} row ${e.row}: ${e.message}`)).slice(0, 6).map((text) => (
            <p key={text} className="muted small">{text}</p>
          ))}
        </>
      )}
    </div>
  );
}

function LiveFeed() {
  const base = agent.connection?.url;
  if (!base) return null; // the in-browser engine has no address to push to
  return (
    <div className="card">
      <h2>Live feed for your developers (optional)</h2>
      <p className="muted">
        Instead of uploading files, your ERP can push changes to your own agent the moment they happen. Use the agent
        token as the key; events never pass through this site.
      </p>
      <pre className="code-block">{`curl -X POST ${base}/events \\\n  -H "X-API-Key: <your agent token>" -H "Content-Type: application/json" \\\n  -d '{"id":"erp-1","entity_type":"item","entity_id":"SKU001","field":"stock_qty","new_value":4}'`}</pre>
    </div>
  );
}

function Wizard({ dataset, datasets, onImported }) {
  const spec = datasets.find((d) => d.name === dataset);
  const [file, setFile] = useState(null); // { name, text }
  const [overrides, setOverrides] = useState(null); // user-edited mapping, null = let the server decide
  const [dateFormat, setDateFormat] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [done, setDone] = useState(null);
  const hasDates = spec.fields.some((f) => f.kind === "date" || f.kind === "datetime");

  useEffect(() => {
    setFile(null); setOverrides(null); setDateFormat(null); setPreview(null); setError(null); setSkipInvalid(false);
  }, [dataset]);

  useEffect(() => {
    if (!file) return undefined;
    let cancelled = false;
    setBusy(true);
    const timer = setTimeout(() => {
      api
        .importPreview(dataset, { filename: file.name, csv_text: file.text, mapping: overrides, date_format: dateFormat })
        .then((result) => { if (!cancelled) { setPreview(result); setError(null); } })
        .catch((err) => { if (!cancelled) { setPreview(null); setError(err.message); } })
        .finally(() => { if (!cancelled) setBusy(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [file, dataset, overrides, dateFormat]);

  const mapping = overrides ?? preview?.mapping ?? {};
  const activeDateFormat = dateFormat ?? preview?.date_format ?? "auto";

  async function pick(event) {
    const chosen = event.target.files?.[0];
    if (!chosen) return;
    setDone(null); setOverrides(null); setDateFormat(null); setPreview(null); setSkipInvalid(false);
    if (chosen.size > MAX_BYTES) {
      setFile(null);
      setError("This file is over 14 MB. Split it and upload it in parts.");
      return;
    }
    setError(null);
    setFile({ name: chosen.name, text: await chosen.text() });
  }

  function remap(field, column) {
    const next = { ...mapping };
    if (column) next[field] = column; else delete next[field];
    setOverrides(next);
  }

  async function commit() {
    setBusy(true);
    try {
      const run = await api.importCommit(dataset, {
        filename: file.name, csv_text: file.text, mapping, date_format: activeDateFormat, skip_invalid: skipInvalid,
      });
      setDone(run);
      setFile(null); setPreview(null); setOverrides(null);
      onImported();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const canImport = preview && preview.missing_required.length === 0 && preview.valid_rows > 0
    && (preview.error_rows === 0 || skipInvalid);

  return (
    <div className="card">
      <h2>{spec.title}</h2>
      <p className="muted">{spec.description}</p>
      {spec.depends_on.length > 0 && (
        <p className="muted small">Import {spec.depends_on.join(" and ").replace(/_/g, " ")} first, so references can be checked.</p>
      )}
      <p className="small">
        Expected columns:{" "}
        {spec.fields.map((f, i) => (
          <span key={f.name}>{i > 0 && ", "}<code title={f.description}>{f.name}</code>{f.required ? "*" : ""}</span>
        ))}
        . Your own column names are fine; you map them below.
      </p>

      <label className="file-pick">
        <span className="btn btn-primary btn-sm">{file ? "Choose a different file" : "Choose a CSV file"}</span>
        <input type="file" accept=".csv,.tsv,.txt,text/csv" onChange={pick} />
        {file && <span className="muted small">{file.name}</span>}
      </label>

      {done && (
        <div className="banner banner-ok" role="status">
          Imported {done.rows_imported} of {done.rows_total} rows
          {done.rows_rejected ? `, skipped ${done.rows_rejected}` : ""}
          {done.decisions_flagged ? `. ${done.decisions_flagged} decision(s) were flagged by this data.` : "."}
        </div>
      )}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {busy && !preview && <Loading label="Reading file…" />}

      {preview && (
        <>
          <h3 className="wizard-h">1. Match your columns</h3>
          <div className="map-grid">
            {spec.fields.map((f) => (
              <label key={f.name} className={preview.missing_required.includes(f.name) ? "map-missing" : ""}>
                <span>{f.name}{f.required ? " *" : ""}<small>{f.description}</small></span>
                <select value={mapping[f.name] ?? ""} onChange={(e) => remap(f.name, e.target.value)}>
                  <option value="">{f.required ? "— choose a column —" : "— not in my file —"}</option>
                  {preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </label>
            ))}
            {hasDates && (
              <label>
                <span>Date format<small>How dates are written in your file</small></span>
                <select value={activeDateFormat} onChange={(e) => setDateFormat(e.target.value)}>
                  {DATE_FORMATS.map((f) => <option key={f} value={f}>{f === "auto" ? "YYYY-MM-DD (ISO)" : f}</option>)}
                </select>
              </label>
            )}
          </div>

          <h3 className="wizard-h">2. Check the result</h3>
          <p>
            <strong>{preview.valid_rows}</strong> of {preview.total_rows} rows are ready
            {preview.error_rows > 0 && <>, <strong className="text-danger">{preview.error_rows}</strong> have problems</>}.
            {busy && <span className="muted small"> Updating…</span>}
          </p>
          {preview.missing_required.length > 0 && (
            <div className="banner banner-warn">Choose a column for: {preview.missing_required.join(", ")}.</div>
          )}
          {preview.errors.length > 0 && (
            <table className="table">
              <thead><tr><th>Row</th><th>Field</th><th>Problem</th></tr></thead>
              <tbody>
                {preview.errors.map((e, i) => (
                  <tr key={i}><td>{e.row}</td><td>{e.field ?? "—"}</td><td>{e.message}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {preview.sample.length > 0 && (
            <>
              <p className="muted small">First {preview.sample.length} rows as DecisionWatch will read them:</p>
              <table className="table">
                <thead><tr>{Object.keys(preview.sample[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                <tbody>
                  {preview.sample.map((row, i) => (
                    <tr key={i}>{Object.keys(preview.sample[0]).map((k) => <td key={k}>{formatCell(row[k])}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className="wizard-actions">
            {preview.error_rows > 0 && (
              <label className="check">
                <input type="checkbox" checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} />
                Skip the {preview.error_rows} problem row(s) and import the rest
              </label>
            )}
            <button className="btn btn-primary" disabled={!canImport || busy} onClick={commit}>
              {busy ? "Working…" : `Import ${preview.valid_rows} rows`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

const formatCell = (value) => (value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value));

export default function Connect() {
  const { signedIn } = useWorkspace();
  const datasets = useAsync(() => api.importDatasets(), []);
  const [selected, setSelected] = useState("suppliers");
  const [tick, setTick] = useState(0);
  const runs = useAsync(() => (signedIn ? api.importRuns() : Promise.resolve([])), [signedIn, tick]);

  const lastRun = useMemo(() => {
    const byDataset = {};
    (runs.data ?? []).forEach((run) => { byDataset[run.dataset] ??= run; });
    return byDataset;
  }, [runs.data]);

  if (!signedIn) {
    return (
      <>
        <PageHeader title="Connect your data" subtitle="Bring your own ERP data into a private workspace." />
        <Empty title="Sign in to connect your ERP">
          <Link to="/signup" className="btn btn-primary btn-sm">Start your free 1-month trial</Link>{" "}
          <Link to="/login" className="btn btn-outline btn-sm">Sign in</Link>
        </Empty>
      </>
    );
  }
  if (datasets.loading) return <Loading />;
  if (datasets.error) return <ErrorBanner>{datasets.error}</ErrorBanner>;

  return (
    <>
      <PageHeader
        title="Connect your data"
        subtitle="Upload exports from any ERP, match your columns once, and DecisionWatch starts watching. Files go to your agent, not to this site."
      />
      <div className="dataset-tabs" role="tablist">
        {datasets.data.map((d, i) => (
          <button
            key={d.name} role="tab" aria-selected={selected === d.name}
            className={`dataset-tab${selected === d.name ? " active" : ""}`} onClick={() => setSelected(d.name)}
          >
            <span className="step-num">{i + 1}</span>
            <span>{d.title}<small>{lastRun[d.name] ? `${lastRun[d.name].rows_imported} rows loaded` : "not loaded"}</small></span>
          </button>
        ))}
      </div>
      <Wizard key={selected} dataset={selected} datasets={datasets.data} onImported={() => setTick((n) => n + 1)} />

      <div className="card">
        <h2>Recent imports</h2>
        {(runs.data ?? []).length === 0 ? (
          <p className="muted">Nothing imported yet. Start with your suppliers.</p>
        ) : (
          <table className="table">
            <thead><tr><th>When</th><th>Dataset</th><th>File</th><th>Imported</th><th>Skipped</th></tr></thead>
            <tbody>
              {runs.data.map((run) => (
                <tr key={run.id}>
                  <td>{new Date(run.created_at).toLocaleString()}</td><td>{run.dataset}</td>
                  <td>{run.filename ?? "—"}</td><td>{run.rows_imported}</td><td>{run.rows_rejected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <ErpSync tick={tick} onDone={() => setTick((n) => n + 1)} />
      <LiveFeed />
    </>
  );
}
