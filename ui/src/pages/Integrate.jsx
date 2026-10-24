import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

const ERP_OPTIONS = [
  ["sap_s4hana", "SAP S/4HANA"],
  ["sap_b1", "SAP Business One"],
  ["sap_ecc", "SAP ECC"],
  ["oracle", "Oracle (Fusion / EBS)"],
  ["netsuite", "Oracle NetSuite"],
  ["dynamics_365", "Microsoft Dynamics 365"],
  ["odoo", "Odoo"],
  ["infor", "Infor"],
  ["other", "Other"],
];
const DEPLOYMENTS = [["cloud", "Cloud"], ["on_prem", "On-premises"], ["hybrid", "Hybrid"]];
const METHODS = [
  ["rest_api", "REST / OData API"],
  ["webhook", "Webhooks or event bus"],
  ["database", "Read-only database access"],
  ["file_export", "Scheduled file export (CSV)"],
  ["not_sure", "Not sure yet"],
];

const GUIDE = [
  {
    title: "Create your free workspace",
    body: "Sign up with your work email. You get a private workspace and a free one-month trial. No card, and nothing to install.",
  },
  {
    title: "Export your data from your ERP",
    body: "Any ERP, including in-house systems, can export CSV. You need four short reports: suppliers (vendor master), items (SKU master), purchase orders (open and recent, ideally with the planner's note) and stock levels. Column names don't matter.",
  },
  {
    title: "Upload and match your columns",
    body: "In Connect data, choose a file and tell DecisionWatch which of your columns is which. Common names (SKU, Vendor Code, PO No, Qty…) are matched for you, and your mapping is saved so the next upload is one click. Numbers like 1,20,000 and dates like 15/03/2025 are handled.",
  },
  {
    title: "Check the preview, then import",
    body: "Before anything is saved you see how many rows are valid, every problem row with the reason, and the first rows as they will be read. Fix the file or import only the valid rows. Import suppliers first, then items, purchase orders and stock.",
  },
  {
    title: "Keep it fresh",
    body: "Re-upload stock or a changes file whenever you like; re-uploads update existing rows instead of duplicating them. For real-time updates, generate an ingest key in Connect data and have your ERP or developers send changes as they happen:",
    code: `curl -X POST https://<your-site>/api/events \
  -H "X-API-Key: <your-ingest-key>" -H "Content-Type: application/json" \
  -d '{"id":"erp-90210","entity_type":"item","entity_id":"SKU001","field":"stock_qty","new_value":4}'`,
  },
  {
    title: "Review and confirm assumptions",
    body: "Open the console, run extraction on a few decisions, and confirm, edit or reject each proposed condition. Nothing is monitored until a planner confirms it.",
  },
  {
    title: "Go live",
    body: "Check the Morning Brief each day. Add your team before the trial ends. DecisionWatch only reads what you give it and never writes back to your ERP.",
  },
];

const EMPTY = {
  company_name: "", contact_name: "", contact_email: "", contact_phone: "", job_title: "",
  erp_system: "sap_s4hana", erp_version: "", deployment: "cloud", integration_method: "rest_api",
  monthly_po_volume: "", planner_count: "", notes: "", consent: false,
};

function toPayload(form) {
  const payload = { ...form };
  ["monthly_po_volume", "planner_count"].forEach((key) => {
    payload[key] = form[key] === "" ? null : Number(form[key]);
  });
  ["contact_phone", "job_title", "erp_version", "notes"].forEach((key) => {
    payload[key] = form[key].trim() || null;
  });
  return payload;
}

export default function Integrate() {
  const [form, setForm] = useState(EMPTY);
  const [state, setState] = useState({ status: "idle", error: null, result: null });

  const set = (key) => (event) =>
    setForm((prev) => ({
      ...prev,
      [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
    }));

  async function submit(event) {
    event.preventDefault();
    setState({ status: "sending", error: null, result: null });
    try {
      const result = await api.createIntegrationRequest(toPayload(form));
      setState({ status: "done", error: null, result });
      setForm(EMPTY);
    } catch (error) {
      setState({ status: "idle", error: error.message, result: null });
    }
  }

  const trialEnd = state.result && new Date(state.result.trial_ends_at).toLocaleDateString();

  return (
    <>
      <section className="hero hero-compact">
        <div className="container narrow">
          <span className="eyebrow">Enterprise integration</span>
          <h1>Connect DecisionWatch to your ERP.</h1>
          <p className="lead">
            Tell us about your landscape and try DecisionWatch on your own data{" "}
            <strong>free for one month</strong>. No card, no commitment.
          </p>
          <div className="hero-actions">
            <Link to="/signup" className="btn btn-primary">Create your free workspace</Link>
            <Link to="/integrate#guide" className="btn btn-outline">See how it works</Link>
          </div>
        </div>
      </section>

      <section className="section" id="request">
        <div className="container narrow">
          <span className="eyebrow">Need a hand?</span>
          <h2>Tell us about your ERP</h2>
          <p className="section-intro">Optional. Most teams connect themselves in minutes, but if you run a custom ERP or want help with the first import, tell us about your setup and we will get in touch.</p>
          {state.status === "done" ? (
            <div className="notice notice-ok" role="status">
              <strong>Thanks, your request is in.</strong> We will contact you within two business days. You can already{" "}
              <Link to="/signup">create your free workspace</Link> (one month free, until {trialEnd} if you start today).
            </div>
          ) : (
            <form className="request-form" onSubmit={submit}>
              <fieldset>
                <legend>Contact</legend>
                <label>Company *<input required value={form.company_name} onChange={set("company_name")} maxLength={255} /></label>
                <label>Your name *<input required value={form.contact_name} onChange={set("contact_name")} maxLength={255} /></label>
                <label>Work email *<input required type="email" value={form.contact_email} onChange={set("contact_email")} maxLength={255} /></label>
                <label>Phone<input type="tel" value={form.contact_phone} onChange={set("contact_phone")} maxLength={64} /></label>
                <label>Job title<input value={form.job_title} onChange={set("job_title")} maxLength={128} /></label>
              </fieldset>
              <fieldset>
                <legend>ERP landscape</legend>
                <label>ERP system *
                  <select value={form.erp_system} onChange={set("erp_system")}>
                    {ERP_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label>Version / release<input value={form.erp_version} onChange={set("erp_version")} placeholder="e.g. S/4HANA 2023" maxLength={128} /></label>
                <label>Hosting *
                  <select value={form.deployment} onChange={set("deployment")}>
                    {DEPLOYMENTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label>Preferred integration method *
                  <select value={form.integration_method} onChange={set("integration_method")}>
                    {METHODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label>Purchase orders per month<input type="number" min="0" value={form.monthly_po_volume} onChange={set("monthly_po_volume")} /></label>
                <label>Number of planners<input type="number" min="0" value={form.planner_count} onChange={set("planner_count")} /></label>
              </fieldset>
              <label className="wide">Anything else we should know?
                <textarea rows={4} value={form.notes} onChange={set("notes")} maxLength={2000} placeholder="Custom modules, security requirements, timelines…" />
              </label>
              <p className="muted small">Do not include passwords, tokens or other credentials here.</p>
              <label className="check">
                <input type="checkbox" checked={form.consent} onChange={set("consent")} required />
                I agree to be contacted about my ERP integration. *
              </label>
              {state.error && <div className="notice notice-error" role="alert">{state.error}</div>}
              <button className="btn btn-primary" type="submit" disabled={state.status === "sending"}>
                {state.status === "sending" ? "Sending…" : "Request help with my ERP"}
              </button>
            </form>
          )}
        </div>
      </section>

      <section className="section section-alt" id="guide">
        <div className="container">
          <span className="eyebrow">Step-by-step guide</span>
          <h2>How to integrate DecisionWatch with your ERP</h2>
          <p className="section-intro">
            You do not need our code or an IT project. Export from your ERP, upload in your browser, and match
            your columns once. DecisionWatch only reads what you give it, so your system of record stays untouched.
          </p>
          <ol className="steps guide-steps">
            {GUIDE.map((step, index) => (
              <li key={step.title}>
                <span className="step-num">{index + 1}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                  {step.code && <pre className="code-block">{step.code}</pre>}
                </div>
              </li>
            ))}
          </ol>
          <p className="muted">
            Your free trial lasts one month from the day you create your workspace.{" "}
            <Link to="/signup">Start now</Link>, or <Link to="/console">look around the demo console</Link> first.
          </p>
        </div>
      </section>
    </>
  );
}
