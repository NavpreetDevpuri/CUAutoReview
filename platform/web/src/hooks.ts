import { useCallback, useEffect, useRef, useState } from "react";
import { useDataProvider } from "react-admin";
import { apiRequest } from "./api";

export interface LoadState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
  refreshQuietly: () => Promise<void>;
}

export function useApi<T>(path: string | null, reloadKey = 0): LoadState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const refreshing = useRef(false);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  const refreshQuietly = useCallback(async () => {
    if (!path || refreshing.current) return;
    refreshing.current = true;
    try { setData(await apiRequest<T>(path)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Request failed"); }
    finally { refreshing.current = false; }
  }, [path]);
  useEffect(() => {
    let alive = true;
    if (!path) { setLoading(false); setData(null); setError(""); return () => { alive = false; }; }
    setLoading(true);
    setError("");
    apiRequest<T>(path)
      .then(value => { if (alive) setData(value); })
      .catch(reason => { if (alive) setError(reason instanceof Error ? reason.message : "Request failed"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [path, reloadKey, nonce]);
  return { data, loading, error, reload, refreshQuietly };
}

export function useResourceList<T>(resource: string, reloadKey = 0): Omit<LoadState<T[]>, "data"> & { data: T[]; total: number } {
  const provider = useDataProvider();
  const [data, setData] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const refreshing = useRef(false);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  const refreshQuietly = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const result = await provider.getList(resource, {
        pagination: { page: 1, perPage: 1000 },
        sort: { field: "updated_at", order: "DESC" },
        filter: {},
      });
      setData(result.data as T[]);
      setTotal(result.total ?? result.data.length);
      setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load records"); }
    finally { refreshing.current = false; }
  }, [provider, resource]);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    provider.getList(resource, {
      pagination: { page: 1, perPage: 1000 },
      sort: { field: "updated_at", order: "DESC" },
      filter: {},
    }).then(result => {
      if (alive) { setData(result.data as T[]); setTotal(result.total ?? result.data.length); }
    }).catch(reason => {
      if (alive) setError(reason instanceof Error ? reason.message : "Could not load records");
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [provider, resource, reloadKey, nonce]);
  return { data, total, loading, error, reload, refreshQuietly };
}
