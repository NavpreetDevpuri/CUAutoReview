export interface PageEnvelope<T> {
  items: T[];
  total: number;
  /** True when the page limit stopped collection before `total` records were read. */
  truncated: boolean;
}

export interface PagingOptions {
  /** Records requested per page; must not exceed the endpoint's server-side cap. */
  pageSize: number;
  /** Upper bound on requests so a misreported total cannot loop forever. */
  maxPages?: number;
}

export const DEFAULT_MAX_PAGES = 50;

// Page sizes match the server-side caps in platform/backend/app/main.py.
/** Datasets and runs: read the whole catalog. */
export const CATALOG_PAGING: PagingOptions = { pageSize: 200 };
/** Tasks in one run: read every member so pickers and next/previous reach all of them. */
export const RUN_TASK_PAGING: PagingOptions = { pageSize: 500, maxPages: 200 };
/** Append-only logs (activity, jobs): newest page only, with a visible truncation note. */
export const LATEST_PAGE: PagingOptions = { pageSize: 500, maxPages: 1 };

export function withPageParams(path: string, page: number, perPage: number): string {
  const index = path.indexOf("?");
  const base = index === -1 ? path : path.slice(0, index);
  const query = new URLSearchParams(index === -1 ? "" : path.slice(index + 1));
  query.set("page", String(page));
  query.set("per_page", String(perPage));
  return `${base}?${query.toString()}`;
}

export function pageItems<T>(value: unknown): { items: T[]; total: number } {
  if (Array.isArray(value)) return { items: value as T[], total: value.length };
  const body = value as { items?: unknown; total?: unknown } | null;
  const items = Array.isArray(body?.items) ? body.items as T[] : [];
  const total = typeof body?.total === "number" && Number.isFinite(body.total) ? body.total : items.length;
  return { items, total };
}

export async function collectPages<T>(fetchPage: (page: number) => Promise<unknown>, maxPages = DEFAULT_MAX_PAGES): Promise<PageEnvelope<T>> {
  const items: T[] = [];
  let total = 0;
  for (let page = 1; page <= Math.max(1, maxPages); page += 1) {
    const result = pageItems<T>(await fetchPage(page));
    items.push(...result.items);
    total = result.total;
    if (!result.items.length || items.length >= total) break;
  }
  return { items, total: Math.max(total, items.length), truncated: items.length < total };
}
