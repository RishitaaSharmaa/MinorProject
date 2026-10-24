import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { agent, api } from "../api";
import { useWorkspace } from "../WorkspaceContext";

const COMMAND = `DB_PASSWORD=<choose-a-password> \
AGENT_TOKEN=<long-random-secret> \
DECISIONWATCH_SITE=${typeof window === "undefined" ? "" : window.location.origin} \
docker compose -f docker-compose.agent.yml up -d --build`;

// Connect this browser to an agent running inside the customer's own network. The address and
// token are kept in this browser only; the hosted site never receives them or any of the data.
export default function Agent() {
  const { signedIn } = useWorkspace();
  const [form, setForm] = useState({ url: agent.connection?.url ?? "http://localhost:8000", token: "" });
  const [state, setState] = useState({ busy: false, error: null });

  if (!signedIn) return <Navigate to="/signup" state={{ from: "/agent" }} replace />;
  if (agent.connection) return <Navigate to="/console/connect" replace />;

  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  function useBrowser() {
    agent.useLocal();
    window.location.assign("/console/connect");
  }

  async function submit(event) {
    event.preventDefault();
    setState({ busy: true, error: null });
    try {
      const me = await api.probeAgent(form.url, form.token);
      if (!me.agent) throw new Error("That address is not a DecisionWatch agent.");
      agent.connect(form.url, form.token);
      window.location.assign("/console/connect");
    } catch (error) {
      setState({
        busy: false,
        error: error instanceof TypeError || /Could not reach/.test(error.message)
          ? "Could not reach the agent. Check the address, that it is running, and that it allows this site (DECISIONWATCH_SITE)."
          : error.message,
      });
    }
  }

  return (
    <section className="section">
      <div className="container auth-wrap">
        <span className="eyebrow">Your data stays with you</span>
        <h1 className="auth-title">Where should your data live?</h1>
        <div className="card">
          <h2>Just this browser (no setup)</h2>
          <p className="muted">
            Best for a small team or a trial. DecisionWatch runs inside this page: files you import are processed
            here and saved in this browser only. Nothing is uploaded, and there is nothing to install. The first
            start downloads about 20 MB once. Data is tied to this browser and device, so clearing site data erases it.
          </p>
          <button className="btn btn-primary" type="button" onClick={useBrowser}>Use this browser</button>
        </div>
        <h2>Or connect your own server</h2>
        <p className="muted">
          For several users or live ERP feeds, run the DecisionWatch agent on any server in your network. Your ERP data is stored and
          processed there; this site only provides the app. Your browser talks to the agent directly.
        </p>
        <ol className="muted">
          <li>Start the agent with one command:
            <pre className="code-block" style={{ whiteSpace: "pre-wrap" }}>{COMMAND}</pre>
          </li>
          <li>Enter its address and token below.</li>
        </ol>
        <form className="request-form" onSubmit={submit}>
          <label>Agent address *<input required type="url" value={form.url} onChange={set("url")} autoComplete="off" /></label>
          <label>Agent token *<input required type="password" value={form.token} onChange={set("token")} autoComplete="off" /></label>
          {state.error && <div className="notice notice-error" role="alert">{state.error}</div>}
          <button className="btn btn-primary" type="submit" disabled={state.busy}>
            {state.busy ? "Checking…" : "Connect"}
          </button>
        </form>
        <p className="muted small">Browsers only allow plain http for localhost; use https for an agent on another host.</p>
        <p className="muted small"><Link to="/console/account">Account &amp; billing</Link></p>
      </div>
    </section>
  );
}
