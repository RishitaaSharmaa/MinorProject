import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useWorkspace } from "./WorkspaceContext";
import { DATASET_END } from "./format";

const AsOfContext = createContext(null);

// Holds the simulated date. Confirming an assumption never changes its status
// by itself -- only a recheck detects that a later event broke it -- so every
// date change triggers a recheck, and pages wait for `synced === asOf`.
export function AsOfProvider({ children }) {
  const { signedIn, hasAgent } = useWorkspace();
  const idle = signedIn && !hasAgent; // an account with no agent has no data to recheck
  // Demo data is a fixed simulated calendar; a real workspace is always "today".
  const [asOf, setAsOf] = useState(signedIn ? new Date().toISOString().slice(0, 10) : DATASET_END);
  const [synced, setSynced] = useState(null);
  const [recheckError, setRecheckError] = useState(null);
  const [lastRecheck, setLastRecheck] = useState(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (idle) {
      setSynced(asOf);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .recheck(asOf)
        .then((summary) => {
          if (cancelled) return;
          setLastRecheck(summary);
          setRecheckError(null);
          setSynced(asOf);
        })
        .catch((error) => {
          if (cancelled) return;
          setRecheckError(error.message);
          setSynced(asOf);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [asOf, nonce, idle]);

  const value = useMemo(
    () => ({
      asOf,
      setAsOf,
      ready: synced === asOf,
      recheckError,
      lastRecheck,
      recheckNow: () => {
        setSynced(null);
        setNonce((n) => n + 1);
      },
    }),
    [asOf, synced, recheckError, lastRecheck],
  );
  return <AsOfContext.Provider value={value}>{children}</AsOfContext.Provider>;
}

export const useAsOf = () => useContext(AsOfContext);
