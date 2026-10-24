import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { agent, api } from "../api";
import { useWorkspace } from "../WorkspaceContext";

// One form for both modes; sign-up also creates the workspace and starts the 30-day trial.
export default function Auth({ mode }) {
  const signup = mode === "signup";
  const { signedIn, enter } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ company_name: "", name: "", email: "", password: "" });
  const [state, setState] = useState({ busy: false, error: null });

  if (signedIn) return <Navigate to="/console/brief" replace />;

  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    setState({ busy: true, error: null });
    try {
      const result = signup
        ? await api.signup(form)
        : await api.login({ email: form.email, password: form.password });
      await enter(result);
      navigate(location.state?.from ?? (agent.connection ? "/console/brief" : "/agent"), { replace: true });
    } catch (error) {
      setState({ busy: false, error: error.message });
    }
  }

  return (
    <section className="section">
      <div className="container auth-wrap">
        <span className="eyebrow">{signup ? "Free for 1 month" : "Welcome back"}</span>
        <h1 className="auth-title">{signup ? "Create your workspace" : "Sign in"}</h1>
        <p className="muted">
          {signup
            ? "Create your account, then connect an agent that keeps your ERP data inside your own network. No card needed."
            : "Sign in to your DecisionWatch workspace."}
        </p>
        <form className="request-form" onSubmit={submit}>
          {signup && (
            <>
              <label>Company *<input required value={form.company_name} onChange={set("company_name")} maxLength={255} autoComplete="organization" /></label>
              <label>Your name *<input required value={form.name} onChange={set("name")} maxLength={255} autoComplete="name" /></label>
            </>
          )}
          <label>Work email *<input required type="email" value={form.email} onChange={set("email")} maxLength={255} autoComplete="email" /></label>
          <label>Password *
            <input
              required type="password" value={form.password} onChange={set("password")}
              minLength={signup ? 8 : undefined} maxLength={128}
              autoComplete={signup ? "new-password" : "current-password"}
            />
          </label>
          {signup && <p className="muted small">At least 8 characters.</p>}
          {state.error && <div className="notice notice-error" role="alert">{state.error}</div>}
          <button className="btn btn-primary" type="submit" disabled={state.busy}>
            {state.busy ? "Please wait…" : signup ? "Start my free trial" : "Sign in"}
          </button>
        </form>
        <p className="muted small">
          {signup ? <>Already have a workspace? <Link to="/login">Sign in</Link></> : <>New here? <Link to="/signup">Create a workspace</Link></>}
        </p>
      </div>
    </section>
  );
}
