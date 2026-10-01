import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { DATASET_END } from "./format";

const AsOfContext = createContext(null);

// Holds the simulated date. Confirming an assumption never changes its status
// by itself -- only a recheck detects that a later event broke it -- so every
// date change triggers a recheck, and pages wait for `synced === asOf`.
export function AsOfProvider({ children }) {
  const [asOf, setAsOf] = useState(DATASET_END);
  const [synced, setSynced] = useState(null);
  const [recheckError, setRecheckError] = useState(null);
  const [lastRecheck, setLastRecheck] = useState(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
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
  }, [asOf, nonce]);

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
