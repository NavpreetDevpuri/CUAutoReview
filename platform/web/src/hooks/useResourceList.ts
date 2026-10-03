import { useCallback, useEffect, useRef, useState } from "react";
import { useDataProvider } from "react-admin";
import { collectPages } from "../api/pagination";
import { endsSession } from "../api/sessionErrors";
import { failureMessage, type LoadState } from "./useApi";

/** Largest page every react-admin resource list endpoint accepts. */
const RESOURCE_PAGE_SIZE = 200;

/** Lists a react-admin resource across all pages. Pass `null` to skip the request entirely. */
export function useResourceList<T>(resource: string | null, reloadKey = 0): Omit<LoadState<T[]>, "data"> & { data: T[]; total: number } {
  const provider = useDataProvider();
  const [data, setData] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(Boolean(resource));
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);
  const refreshing = useRef(false);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  const fetchAll = useCallback((name: string) => collectPages<T>(page => provider.getList(name, {
    pagination: { page, perPage: RESOURCE_PAGE_SIZE },
    sort: { field: "updated_at", order: "DESC" },
    filter: {},
  }).then(result => ({ items: result.data, total: result.total ?? result.data.length }))), [provider]);
  const refreshQuietly = useCallback(async () => {
    if (!resource || refreshing.current) return;
    refreshing.current = true;
    const started = generation.current;
    try {
      const result = await fetchAll(resource);
      if (generation.current === started) { setData(result.items); setTotal(result.total); setError(""); }
    } catch (reason) {
      if (generation.current === started && endsSession(reason)) setError(failureMessage(reason, "Could not load records"));
    } finally { refreshing.current = false; }
  }, [fetchAll, resource]);
  useEffect(() => {
    const started = ++generation.current;
    setError("");
    if (!resource) { setData([]); setTotal(0); setLoading(false); return; }
    setLoading(true);
    fetchAll(resource).then(result => {
      if (generation.current === started) { setData(result.items); setTotal(result.total); }
    }).catch(reason => {
      if (generation.current === started) setError(failureMessage(reason, "Could not load records"));
    }).finally(() => { if (generation.current === started) setLoading(false); });
  }, [fetchAll, resource, reloadKey, nonce]);
  return { data, total, loading, error, reload, refreshQuietly };
}
