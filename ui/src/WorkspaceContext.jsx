import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { agent, api, auth } from "./api";
import { Loading } from "./components/ui";

const WorkspaceContext = createContext(null);

// Knows whether the visitor is in the shared demo workspace or signed in to their own.
// `workspace.demo` is true for the demo; otherwise `workspace.tenant`/`user` describe them.
export function WorkspaceProvider({ children }) {
  const [workspace, setWorkspace] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setWorkspace(await api.me());
      setError(null);
    } catch (err) {
      // An expired or revoked token: fall back to the demo/sign-in state.
      if (auth.token) {
        auth.token = null;
        try {
          setWorkspace(await api.me());
          return;
        } catch { /* fall through to the error state */ }
      }
      setError(err.message);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo(() => ({
    workspace,
    signedIn: Boolean(workspace && !workspace.demo),
    hasAgent: Boolean(agent.connection),
    refresh,
    async enter(result) {
      auth.token = result.token;
      setWorkspace(result.workspace);
    },
    async leave() {
      agent.disconnect(); // an agent belongs to the signed-in account; don't leave it behind for the next one
      try { await api.logout(); } catch { /* token may already be invalid */ }
      auth.token = null;
      await refresh();
    },
  }), [workspace, refresh]);

  if (error && !workspace) {
    return <div className="container narrow section"><div className="banner banner-danger" role="alert">{error}</div></div>;
  }
  if (!workspace) return <Loading label="Loading workspace…" />;
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export const useWorkspace = () => useContext(WorkspaceContext);
