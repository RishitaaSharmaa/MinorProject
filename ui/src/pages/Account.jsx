import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorBanner, Loading, PageHeader } from "../components/ui";
import { useWorkspace } from "../WorkspaceContext";

const EMPTY = { billing_name: "", billing_email: "", billing_address: "", billing_country: "", tax_id: "" };

// The only thing this site stores about a customer: who they are and how to bill them.
export default function Account() {
  const { workspace, signedIn } = useWorkspace();
  const [form, setForm] = useState(EMPTY);
  const [state, setState] = useState({ loading: true, busy: false, error: null, saved: false });

  useEffect(() => {
    if (!signedIn) return;
    api.billing()
      .then((data) => {
        setForm(Object.fromEntries(Object.keys(EMPTY).map((k) => [k, data[k] ?? ""])));
        setState((s) => ({ ...s, loading: false }));
      })
      .catch((error) => setState((s) => ({ ...s, loading: false, error: error.message })));
  }, [signedIn]);

  if (!signedIn) {
    return (
      <>
        <PageHeader title="Account & billing" />
        <Empty title="Sign in to manage your account">
          <Link to="/login" className="btn btn-primary btn-sm">Sign in</Link>
        </Empty>
      </>
    );
  }
  if (state.loading) return <Loading />;

  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setState((s) => ({ ...s, busy: true, error: null, saved: false }));
    try {
      await api.saveBilling(form);
      setState((s) => ({ ...s, busy: false, saved: true }));
    } catch (error) {
      setState((s) => ({ ...s, busy: false, error: error.message }));
    }
  }

  const { tenant, user } = workspace;
  return (
    <>
      <PageHeader title="Account & billing" subtitle="This is everything DecisionWatch stores about you. Your ERP data stays in your own network." />
      <div className="card">
        <h2>Account</h2>
        <p><strong>{tenant.name}</strong><br />{user.name} · {user.email}</p>
        <p className="muted">
          Plan: {tenant.plan}
          {tenant.plan === "trial" && (tenant.trial_expired ? " (ended)" : ` · ${tenant.trial_days_left} day${tenant.trial_days_left === 1 ? "" : "s"} left`)}
        </p>
      </div>
      <form className="card request-form" onSubmit={submit}>
        <h2>Billing details</h2>
        <label>Billing name *<input required value={form.billing_name} onChange={set("billing_name")} maxLength={255} autoComplete="organization" /></label>
        <label>Billing email *<input required type="email" value={form.billing_email} onChange={set("billing_email")} maxLength={255} autoComplete="email" /></label>
        <label>Billing address *<textarea required rows={3} value={form.billing_address} onChange={set("billing_address")} maxLength={1000} autoComplete="street-address" /></label>
        <label>Country *<input required value={form.billing_country} onChange={set("billing_country")} minLength={2} maxLength={64} autoComplete="country-name" /></label>
        <label>Tax / GST / VAT ID<input value={form.tax_id} onChange={set("tax_id")} maxLength={64} /></label>
        <p className="muted small">Card details are never stored here; payment is handled by a payment provider.</p>
        {state.error && <ErrorBanner>{state.error}</ErrorBanner>}
        {state.saved && <div className="banner banner-ok" role="status">Saved.</div>}
        <button className="btn btn-primary" type="submit" disabled={state.busy}>{state.busy ? "Saving…" : "Save billing details"}</button>
      </form>
    </>
  );
}
