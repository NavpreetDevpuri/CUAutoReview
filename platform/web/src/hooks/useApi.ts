import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api/client";
import { collectPages, type PagingOptions, withPageParams } from "../api/pagination";
import { endsSession } from "../api/sessionErrors";

export interface LoadState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
  refreshQuietly: () => Promise<void>;
}

interface Snapshot<T> {
  key: string | null;
  data: T | null;
  error: string;
  settled: boolean;
}

export function failureMessage(reason: unknown, fallback: string): string {
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
  const fetchPath = useCallback(
    (target: string): Promise<T> =>
      pageSize
        ? (collectPages(page => apiRequest<unknown>(withPageParams(target, page, pageSize)), maxPages) as Promise<T>)
        : apiRequest<T>(target),
    [pageSize, maxPages],
  );
  const refreshQuietly = useCallback(async () => {
    if (!path || refreshing.current) return;
    refreshing.current = true;
    const started = generation.current;
    try {
      const value = await fetchPath(path);
      if (generation.current === started)
        setSnapshot(current => (current.key === path ? { key: path, data: value, error: "", settled: true } : current));
    } catch (reason) {
      // A failed background poll keeps the last good data; only a lost session is surfaced.
      if (generation.current === started && endsSession(reason)) {
        setSnapshot(current =>
          current.key === path ? { ...current, error: failureMessage(reason, "Request failed") } : current,
        );
      }
    } finally {
      refreshing.current = false;
    }
  }, [path, fetchPath]);
  useEffect(() => {
    const started = ++generation.current;
    if (!path) {
      setSnapshot({ key: null, data: null, error: "", settled: true });
      return;
    }
    setSnapshot(current => ({
      key: path,
      data: current.key === path ? current.data : null,
      error: "",
      settled: false,
    }));
    fetchPath(path)
      .then(value => {
        if (generation.current === started) setSnapshot({ key: path, data: value, error: "", settled: true });
      })
      .catch(reason => {
        if (generation.current === started)
          setSnapshot(current => ({
            key: path,
            data: current.key === path ? current.data : null,
            error: failureMessage(reason, "Request failed"),
            settled: true,
          }));
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
