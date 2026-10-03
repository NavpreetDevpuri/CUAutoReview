import { useCallback, useEffect, useRef, useState } from "react";
import { useDataProvider } from "react-admin";
import { apiRequest } from "./api";
import { collectPages, withPageParams, type PagingOptions } from "./pagination";
import { endsSession } from "./sessionErrors";

export interface LoadState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
  refreshQuietly: () => Promise<void>;
}

interface Snapshot<T> { key: string | null; data: T | null; error: string; settled: boolean }

function failureMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/**
 * Loads `path`, keyed by path so a route change never exposes the previous record as current.
 * With `paging`, every page is collected and `data` is `{ items, total, truncated }`.
 */
export function useApi<T>(path: string | null, reloadKey = 0, paging?: PagingOptions): LoadState<T> {
  const pageSize = paging?.pageSize;
  const maxPages = paging?.maxPages;
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({ key: null, data: null, error: "", settled: !path });
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);
  const refreshing = useRef(false);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  const fetchPath = useCallback((target: string): Promise<T> => pageSize
    ? collectPages(page => apiRequest<unknown>(withPageParams(target, page, pageSize)), maxPages) as Promise<T>
    : apiRequest<T>(target), [pageSize, maxPages]);
  const refreshQuietly = useCallback(async () => {
    if (!path || refreshing.current) return;
    refreshing.current = true;
    const started = generation.current;
    try {
      const value = await fetchPath(path);
      if (generation.current === started) setSnapshot(current => current.key === path ? { key: path, data: value, error: "", settled: true } : current);
    } catch (reason) {
      // A failed background poll keeps the last good data; only a lost session is surfaced.
      if (generation.current === started && endsSession(reason)) {
        setSnapshot(current => current.key === path ? { ...current, error: failureMessage(reason, "Request failed") } : current);
      }
    } finally { refreshing.current = false; }
  }, [path, fetchPath]);
  useEffect(() => {
    const started = ++generation.current;
    if (!path) { setSnapshot({ key: null, data: null, error: "", settled: true }); return; }
    setSnapshot(current => ({ key: path, data: current.key === path ? current.data : null, error: "", settled: false }));
    fetchPath(path)
      .then(value => { if (generation.current === started) setSnapshot({ key: path, data: value, error: "", settled: true }); })
      .catch(reason => {
        if (generation.current === started) setSnapshot(current => ({ key: path, data: current.key === path ? current.data : null, error: failureMessage(reason, "Request failed"), settled: true }));
      });
  }, [path, reloadKey, nonce, fetchPath]);
  const current = snapshot.key === path;
  return {
    data: current ? snapshot.data : null,
    loading: path ? !current || !snapshot.settled : false,
    error: current ? snapshot.error : "",
    reload,
    refreshQuietly,
  };
}

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
