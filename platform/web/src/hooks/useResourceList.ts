import { useCallback, useEffect, useRef, useState } from "react";
import { useDataProvider } from "react-admin";
import { collectPages } from "../api/pagination";
import { endsSession } from "../api/sessionErrors";
import { failureMessage, type LoadState } from "./useApi";

/** Largest page every react-admin resource list endpoint accepts. */
const RESOURCE_PAGE_SIZE = 200;

interface ListSnapshot<T> {
  key: string | null;
  data: T[];
  total: number;
  error: string;
  settled: boolean;
}

const EMPTY_LIST: never[] = [];

/**
 * Lists a react-admin resource across all pages. Pass `null` to skip the request entirely.
 * State is keyed by resource, so switching resources never exposes the previous list as current.
 */
export function useResourceList<T>(
  resource: string | null,
  reloadKey = 0,
): Omit<LoadState<T[]>, "data"> & { data: T[]; total: number } {
  const provider = useDataProvider();
  const [snapshot, setSnapshot] = useState<ListSnapshot<T>>({
    key: null,
    data: EMPTY_LIST,
    total: 0,
    error: "",
    settled: !resource,
  });
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);
  const refreshing = useRef(false);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  const fetchAll = useCallback(
    (name: string) =>
      collectPages<T>(page =>
        provider
          .getList(name, {
            pagination: { page, perPage: RESOURCE_PAGE_SIZE },
            sort: { field: "updated_at", order: "DESC" },
            filter: {},
          })
          .then(result => ({ items: result.data, total: result.total ?? result.data.length })),
      ),
    [provider],
  );
  const refreshQuietly = useCallback(async () => {
    if (!resource || refreshing.current) return;
    refreshing.current = true;
    const started = generation.current;
    try {
      const result = await fetchAll(resource);
      if (generation.current === started) {
        setSnapshot(current =>
          current.key === resource
            ? { key: resource, data: result.items, total: result.total, error: "", settled: true }
            : current,
        );
      }
    } catch (reason) {
      // A failed background refresh keeps the last good list; only a lost session is surfaced.
      if (generation.current === started && endsSession(reason)) {
        setSnapshot(current =>
          current.key === resource ? { ...current, error: failureMessage(reason, "Could not load records") } : current,
        );
      }
    } finally {
      refreshing.current = false;
    }
  }, [fetchAll, resource]);
  useEffect(() => {
    const started = ++generation.current;
    // A skipped request needs no state change: results are derived from the snapshot's key.
    if (!resource) return;
    setSnapshot(current => ({
      key: resource,
      data: current.key === resource ? current.data : EMPTY_LIST,
      total: current.key === resource ? current.total : 0,
      error: "",
      settled: false,
    }));
    fetchAll(resource)
      .then(result => {
        if (generation.current === started) {
          setSnapshot({ key: resource, data: result.items, total: result.total, error: "", settled: true });
        }
      })
      .catch(reason => {
        if (generation.current === started) {
          setSnapshot(current => ({
            ...current,
            key: resource,
            error: failureMessage(reason, "Could not load records"),
            settled: true,
          }));
        }
      });
  }, [fetchAll, resource, reloadKey, nonce]);
  const current = snapshot.key === resource;
  return {
    data: current ? snapshot.data : EMPTY_LIST,
    total: current ? snapshot.total : 0,
    loading: resource ? !current || !snapshot.settled : false,
    error: current ? snapshot.error : "",
    reload,
    refreshQuietly,
  };
}
