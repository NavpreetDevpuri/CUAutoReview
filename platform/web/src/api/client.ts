import type { AuthProvider, DataProvider, Identifier, RaRecord } from "react-admin";
import { endsSession } from "./sessionErrors";
import type { ApiErrorShape, ListResult, SessionUser } from "./types";
import { asRecord } from "../lib/records";

export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map(item => {
        const value = item as { loc?: unknown[]; msg?: string };
        return `${value.loc?.join(".") || "Input"}: ${value.msg || "Invalid value"}`;
      })
      .join("; ");
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string")
    return detail.message;
  return fallback;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");
  const response = await fetch(path.startsWith("/api") ? path : `/api${path.startsWith("/") ? path : `/${path}`}`, {
    ...init,
    headers,
    credentials: "include",
  });
  const raw = response.status === 204 ? null : await response.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }
  if (!response.ok) {
    const body = payload as ApiErrorShape | null;
    const message =
      typeof body === "object" && body
        ? errorMessage(body.detail, body.message || response.statusText)
        : typeof body === "string"
          ? body
          : response.statusText;
    throw new ApiError(message || `Request failed (${response.status})`, response.status, payload);
  }
  return payload as T;
}

function listEnvelope(value: unknown): { data: Record<string, unknown>[]; total: number } {
  const body = value as { items?: Record<string, unknown>[]; data?: Record<string, unknown>[]; total?: number };
  const data = Array.isArray(body?.items)
    ? body.items
    : Array.isArray(body?.data)
      ? body.data
      : Array.isArray(value)
        ? (value as Record<string, unknown>[])
        : [];
  return { data, total: Number.isFinite(body?.total) ? Number(body.total) : data.length };
}

function recordId(resource: string, value: Record<string, unknown>): string {
  const id =
    value.id ??
    value[resource.slice(0, -1) + "_id"] ??
    value.dataset_id ??
    value.batch_id ??
    value.task_id ??
    value.user_id ??
    value.team_id;
  return String(id ?? "");
}

/** Unwrap an optional `{ data }` envelope from a single-record response. */
function recordBody(body: unknown): Record<string, unknown> {
  return asRecord(body && typeof body === "object" && "data" in body ? (body as { data: unknown }).data : body);
}

/** Give a record the `id` react-admin keys on, falling back to resource-specific ID fields. */
function withId<RecordType extends RaRecord>(resource: string, value: Record<string, unknown>): RecordType {
  return { ...value, id: (value.id ?? recordId(resource, value)) as Identifier } as RecordType;
}

export const dataProvider: DataProvider = {
  async getList(resource, params) {
    const query = new URLSearchParams();
    if (params.pagination) {
      query.set("page", String(params.pagination.page));
      query.set("per_page", String(params.pagination.perPage));
    }
    if (params.sort?.field) {
      query.set("sort", params.sort.field);
      query.set("order", params.sort.order.toLowerCase());
    }
    for (const [key, value] of Object.entries(params.filter || {})) {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    }
    const suffix = query.size ? `?${query.toString()}` : "";
    const result = listEnvelope(await apiRequest<unknown>(`/${resource}${suffix}`));
    return { data: result.data.map(item => withId(resource, item)), total: result.total };
  },
  async getOne(resource, params) {
    const body = await apiRequest<Record<string, unknown>>(`/${resource}/${encodeURIComponent(String(params.id))}`);
    return { data: withId(resource, recordBody(body)) };
  },
  async getMany(resource, params) {
    const records = await Promise.all(params.ids.map(id => this.getOne(resource, { id })));
    return { data: records.map(result => result.data) };
  },
  async getManyReference(resource, params) {
    return this.getList(resource, { ...params, filter: { ...params.filter, [params.target]: params.id } });
  },
  async create(resource, params) {
    const body = await apiRequest<Record<string, unknown>>(`/${resource}`, {
      method: "POST",
      body: JSON.stringify(params.data),
    });
    return { data: withId(resource, recordBody(body)) };
  },
  async update(resource, params) {
    const body = await apiRequest<Record<string, unknown>>(`/${resource}/${encodeURIComponent(String(params.id))}`, {
      method: "PATCH",
      body: JSON.stringify(params.data),
    });
    return { data: withId(resource, recordBody(body)) };
  },
  async updateMany(resource, params) {
    await Promise.all(
      params.ids.map(id =>
        apiRequest(`/${resource}/${encodeURIComponent(String(id))}`, {
          method: "PATCH",
          body: JSON.stringify(params.data),
        }),
      ),
    );
    return { data: params.ids };
  },
  async delete(resource, params) {
    const old = await apiRequest<Record<string, unknown> | null>(
      `/${resource}/${encodeURIComponent(String(params.id))}`,
      { method: "DELETE" },
    );
    return { data: withId(resource, { ...(params.previousData ?? old ?? {}), id: params.id }) };
  },
  async deleteMany(resource, params) {
    await Promise.all(
      params.ids.map(id => apiRequest(`/${resource}/${encodeURIComponent(String(id))}`, { method: "DELETE" })),
    );
    return { data: params.ids };
  },
};

export const authProvider: AuthProvider = {
  async login({ email, password }) {
    await apiRequest<SessionUser>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
  },
  async logout() {
    await apiRequest("/auth/logout", { method: "POST" }).catch(() => undefined);
  },
  async checkAuth() {
    await apiRequest<SessionUser>("/auth/me");
  },
  async checkError(error) {
    if (endsSession(error)) throw error;
  },
  async getIdentity() {
    return apiRequest<SessionUser>("/auth/me");
  },
  async getPermissions() {
    const user = await apiRequest<SessionUser>("/auth/me");
    return user.role;
  },
};

export async function fetchList<T>(path: string): Promise<ListResult<T>> {
  const result = await apiRequest<{ items?: T[]; total?: number } | T[]>(path);
  if (Array.isArray(result)) return { items: result, total: result.length };
  const items = result.items || [];
  return { items, total: result.total ?? items.length };
}
