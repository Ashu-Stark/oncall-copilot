// Thin client for the FastAPI backend. The session token lives in localStorage; every call sends it as a Bearer token.

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";
export type Status = "triggered" | "acknowledged" | "investigating" | "resolved";

export interface User {
  id: number;
  username: string;
  name: string;
  role: "engineer" | "lead";
}

export interface AlertRow {
  id: number;
  name: string;
  summary: string;
  severity: Severity;
  source: string;
  count: number;
  labels: Record<string, unknown>;
  first_seen: string;
  last_seen: string;
}

export interface Incident {
  id: number;
  title: string;
  service: string;
  severity: Severity;
  status: Status;
  assignee: User | null;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  is_demo: boolean;
  simulated_fault: string | null;
  expected_label: string | null;
  resolution: string;
  alert_count: number;
  alerts: AlertRow[];
  verdict: { investigation_id: number; status: string; label: string | null } | null;
  log_lines?: number;
  health?: Record<string, unknown> | null;
}

export interface CheckResult {
  tool: string;
  args: Record<string, unknown>;
  field: string;
  op: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
  evidence: number[];
  evidence_lines?: string[];
}

export interface Step {
  seq: number;
  kind: "alerts" | "query" | "retrieval" | "check" | "verdict";
  title: string;
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  at: string;
}

export interface Investigation {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  label: string | null;
  requested_by: string;
  created_at: string;
  finished_at: string | null;
  error: string;
  steps?: Step[];
}

export interface TimelineEvent {
  id: number;
  at: string;
  kind: string;
  actor: string;
  text: string;
  data: Record<string, unknown>;
}

export interface RunbookSummary {
  id: string;
  title: string;
  severity: string;
  service: string;
  version: number;
  updated_at: string;
  updated_by: string;
}

export interface ValidationError {
  line: number | null;
  message: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "oncall.token";

export const session = {
  get: (): string | null => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* private mode: the session lasts for this page only */
    }
  },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export function authHeaders(): Record<string, string> {
  const t = session.get();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function messageOf(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("; ");
  if (detail && typeof detail === "object" && "errors" in detail) return "The runbook has errors";
  return `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init.headers ?? {}) },
  });
  if (res.status === 401 && !path.startsWith("/auth/login")) onUnauthorized();
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, messageOf(body?.detail, res.status), body?.detail);
  return body as T;
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export function streamUrl(investigationId: number): string {
  return `${BASE}/api/investigations/${investigationId}/stream`;
}
