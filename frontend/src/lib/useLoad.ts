import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../api/client";

export interface LoadState<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  /** Fetch again (e.g. after the user changed something). */
  reload: () => Promise<void>;
}

/**
 * Run an async loader on mount and whenever `deps` change, tracking
 * loading/error state.
 *
 * - Pass `null` as the loader to skip loading (e.g. no tenant selected yet).
 * - If deps change while a request is in flight, the older response is
 *   ignored, so a slow earlier request can never overwrite newer data.
 *
 * Usage:
 *   const cases = useLoad(tenantId ? () => api.listCases(tenantId) : null, [tenantId]);
 */
export function useLoad<T>(loader: (() => Promise<T>) | null, deps: unknown[]): LoadState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(loader !== null);

  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const requestId = useRef(0);

  const reload = useCallback(async () => {
    const current = loaderRef.current;
    const id = ++requestId.current;
    if (current === null) {
      setData(undefined);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(undefined);
    try {
      const result = await current();
      if (id === requestId.current) setData(result);
    } catch (e) {
      if (id === requestId.current) setError(errorMessage(e));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps -- deps are supplied by the caller

  return { data, error, loading, reload };
}
