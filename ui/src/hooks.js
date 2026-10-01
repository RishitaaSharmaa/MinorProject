import { useCallback, useEffect, useState } from "react";

// Runs an async loader whenever `deps` change; `reload` forces a refetch.
export function useAsync(loader, deps, enabled = true) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loader()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error: error.message, loading: false }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
