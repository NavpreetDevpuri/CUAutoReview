import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api/client";
import { failureMessage } from "./useApi";

interface QueryResult<T> {
  key: string;
  data: T | null;
  error: string;
}

export interface PostQueryState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
}

/**
 * Runs a read-only POST query (for example analytics) whenever its path, body or reloadKey changes,
 * or when `reload` is called. Each request has its own key and the stored result names the key it
 * answers, so loading is derived and a slow earlier response never shows as current.
 * Pass `null` as the path to skip the request.
 */
export function usePostQuery<T>(
  path: string | null,
  payload: unknown,
  reloadKey = 0,
  fallbackError = "Request failed",
): PostQueryState<T> {
  const body = JSON.stringify(payload ?? null);
  const [nonce, setNonce] = useState(0);
  const requestKey = path ? `${path}\n${body}\n${reloadKey}\n${nonce}` : null;
  const [result, setResult] = useState<QueryResult<T> | null>(null);
  const latest = useRef<string | null>(null);
  const reload = useCallback(() => setNonce(value => value + 1), []);
  useEffect(() => {
    latest.current = requestKey;
    if (!path || !requestKey) return;
    apiRequest<T>(path, { method: "POST", body })
      .then(data => {
        if (latest.current === requestKey) setResult({ key: requestKey, data, error: "" });
      })
      .catch(reason => {
        if (latest.current === requestKey) {
          setResult({ key: requestKey, data: null, error: failureMessage(reason, fallbackError) });
        }
      });
  }, [path, body, requestKey, fallbackError]);
  const current = result !== null && result.key === requestKey;
  return {
    data: current ? result.data : null,
    loading: requestKey !== null && !current,
    error: current ? result.error : "",
    reload,
  };
}
