export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Auth is now session-cookie-based. Every request includes credentials so the
// session cookie set by /auth/login is sent cross-origin from :3000 → :8000.
// CORS on the backend has allow_credentials=true.
//
// 401s are surfaced as `UnauthorizedError`, which the AuthProvider catches and
// uses to redirect to /login.
export class UnauthorizedError extends Error {
  constructor() {
    super("Not signed in");
    this.name = "UnauthorizedError";
  }
}

// ---------- Active environment ----------
//
// Multi-env: every API call may carry an `?env=<name>` query param. The active
// env is set globally by the Dashboard (from URL ?env= or localStorage) and
// threaded through `withEnv()` into every request. Initial value is null →
// backend resolves to the default env.

const ACTIVE_ENV_STORAGE_KEY = "pipelinepulse:active-env";
let activeEnv: string | null = null;

if (typeof window !== "undefined") {
  try {
    activeEnv = window.localStorage.getItem(ACTIVE_ENV_STORAGE_KEY);
  } catch {
    activeEnv = null;
  }
}

export function getActiveEnv(): string | null {
  return activeEnv;
}

export function setActiveEnv(name: string | null) {
  activeEnv = name && name.trim() ? name : null;
  if (typeof window !== "undefined") {
    try {
      if (activeEnv) window.localStorage.setItem(ACTIVE_ENV_STORAGE_KEY, activeEnv);
      else window.localStorage.removeItem(ACTIVE_ENV_STORAGE_KEY);
    } catch {
      // ignore quota / disabled-storage errors
    }
  }
}

function withEnv(path: string): string {
  if (!activeEnv) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}env=${encodeURIComponent(activeEnv)}`;
}

export type DAG = {
  dag_id: string;
  description?: string | null;
  is_paused?: boolean;
};

export type DAGRun = {
  run_id: string;
  state: "success" | "failed" | "running" | "queued" | string;
  start_date: string | null;
  duration_seconds: number | null;
};

export type Summary = {
  total_runs: number;
  success: number;
  failed: number;
  running: number;
  success_rate: number;
};

export type StuckRun = {
  dag_id: string;
  run_id: string;
  start_date: string;
  elapsed_seconds: number;
  p95_seconds: number;
  threshold_seconds: number;
};

export type AnalyticsResponse = {
  range: "7d" | "30d";
  totals: {
    current: {
      total: number;
      failed: number;
      success_rate: number;
      total_runtime_seconds: number;
      avg_duration_seconds: number;
    };
    previous: {
      total: number;
      failed: number;
      success_rate: number;
      total_runtime_seconds: number;
      avg_duration_seconds: number;
    };
    deltas: {
      total: number | null;
      failed: number | null;
      success_rate: number;
      total_runtime_seconds: number | null;
      avg_duration_seconds: number | null;
    };
  };
  daily: Array<{
    date: string;
    total: number;
    failed: number;
    success: number;
    failure_rate: number;
  }>;
  slowest_dags: Array<{
    dag_id: string;
    total_runs: number;
    failures: number;
    failure_rate: number;
    avg_duration_seconds: number;
  }>;
  most_failures: Array<{
    dag_id: string;
    total_runs: number;
    failures: number;
    failure_rate: number;
    avg_duration_seconds: number;
  }>;
  busy_hours: Array<{ hour: number; total: number; failed: number }>;
};

export type SlaConfig = {
  dag_id: string;
  enabled: boolean;
  deadline_time: string | null;       // "HH:MM"
  deadline_timezone: string | null;   // IANA tz
  max_runtime_minutes: number | null;
};

export type SlaBreach = {
  dag_id: string;
  run_id: string;
  start_date: string;
  kind: "deadline_missed" | "max_runtime";
  message: string;
};

export type SlaAtRisk = { dag_id: string; reason: string };

export type AlertConfig = {
  dag_id: string;
  muted: boolean;
  min_consecutive_failures: number;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  quiet_timezone: string | null;
};

export type RunDiff = {
  baseline: {
    dag_id: string;
    run_id: string;
    state: string;
    start_date: string;
    duration_seconds: number | null;
  } | null;
  baseline_kind?: "last_success" | "explicit";
  current?: {
    dag_id: string;
    run_id: string;
    state: string;
    start_date: string | null;
    duration_seconds: number | null;
  };
  duration_delta_seconds: number | null;
  task_changes: Array<{
    task_id: string;
    current_state: string;
    baseline_state: string;
    state_changed: boolean;
    current_duration: number | null;
    baseline_duration: number | null;
    duration_delta_seconds: number | null;
  }>;
  added_tasks: string[];
  removed_tasks: string[];
};

export type SecretSetting = { set: boolean; db_override: boolean };

export type Settings = {
  webhook_url: SecretSetting;
  gemini_api_key: SecretSetting;
  gemini_model: string;
  sync_interval_minutes: number;
  stuck_multiplier: number;
  stuck_floor_seconds: number;
  stuck_min_history: number;
};

export type SettingsUpdate = Partial<{
  webhook_url: string | null;
  gemini_api_key: string | null;
  gemini_model: string | null;
  sync_interval_minutes: number | null;
  stuck_multiplier: number | null;
  stuck_floor_seconds: number | null;
  stuck_min_history: number | null;
}>;

export type RunAnnotation = {
  dag_id: string;
  run_id: string;
  note: string;
  updated_at: string | null;
};

export type ReportFormat = "md" | "html" | "pdf";
export type ReportRange = "7d" | "30d";

export type ReportHistoryItem = {
  id: number;
  range: ReportRange;
  format: ReportFormat;
  source: "manual" | "scheduled";
  summary_line: string | null;
  delivered: string | null;
  generated_at: string | null;
};

export type ReportSchedule = {
  enabled: boolean;
  frequency: "weekly" | "monthly";
  day_of_week: number;
  day_of_month: number;
  hour: number;
  range: ReportRange;
  format: ReportFormat;
  webhook_url: string | null;
  last_sent_at: string | null;
  global_webhook_configured: boolean;
};

export type CurrentUser = {
  id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
  created_at: string | null;
  last_login_at: string | null;
};

export type ApiTokenInfo = {
  id: number;
  name: string;
  token_prefix: string;
  created_at: string | null;
  last_used_at: string | null;
};

export type NewApiToken = ApiTokenInfo & { plaintext: string };

export type EnvironmentInfo = {
  id: number;
  name: string;
  airflow_base_url: string;
  airflow_username: string | null;
  airflow_public_url: string | null;
  password_set: boolean;
  is_default: boolean;
  enabled: boolean;
};

export type EnvironmentCreate = {
  name: string;
  airflow_base_url: string;
  airflow_username?: string | null;
  airflow_password?: string | null;
  airflow_public_url?: string | null;
  is_default?: boolean;
  enabled?: boolean;
};

export type EnvironmentUpdate = {
  name?: string;
  airflow_base_url?: string;
  airflow_username?: string | null;
  airflow_password?: string | null;
  clear_password?: boolean;
  airflow_public_url?: string | null;
  is_default?: boolean;
  enabled?: boolean;
};

export type TaskInstance = {
  task_id: string;
  state: string;
  duration_seconds: number | null;
  start_date: string | null;
  end_date: string | null;
  try_number: number | null;
  error_message: string | null;
};

export type TaskLogs = {
  logs: string;
  attempt: number;
  empty: boolean;
};

// Endpoints that should NOT have ?env= appended — they're env-agnostic.
// Every other path gets the active env threaded through.
const ENV_AGNOSTIC = [
  "/health",
  "/settings",          // matches /settings, /settings/danger/*  — handled by prefix below
  "/environments",      // managing environments themselves shouldn't filter by active env
  "/reports/schedule",  // (kept env-aware via the dependency, but the path is shared)
];

function shouldSkipEnv(path: string): boolean {
  // strip query string for matching
  const pure = path.split("?")[0];
  if (pure === "/" || pure === "") return true;
  if (pure === "/environments") return true;
  if (pure.startsWith("/environments/")) return true;
  if (pure === "/settings" || pure.startsWith("/settings/")) {
    // Settings endpoints are env-agnostic EXCEPT the danger zone, which IS env-scoped.
    return !pure.startsWith("/settings/danger/");
  }
  if (pure === "/health") return true;
  if (pure.startsWith("/auth/")) return true;
  if (pure === "/api-tokens" || pure.startsWith("/api-tokens/")) return true;
  return false;
}

function buildUrl(path: string): string {
  const final = shouldSkipEnv(path) ? path : withEnv(path);
  return `${API_URL}${final}`;
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = { ...(init?.headers ?? {}) };
  const res = await fetch(buildUrl(path), {
    cache: "no-store",
    credentials: "include",
    ...init,
    headers,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      // ignore — keep generic error
    }
    throw new Error(detail || `${path} → ${res.status}`);
  }
  return res.json();
}

async function blobFetch(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string | null; reportId: number | null; summary: string | null }> {
  const headers = { ...(init?.headers ?? {}) };
  const res = await fetch(buildUrl(path), {
    cache: "no-store",
    credentials: "include",
    ...init,
    headers,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const idHeader = res.headers.get("X-Report-Id");
  const summary = res.headers.get("X-Report-Summary");
  return {
    blob: await res.blob(),
    filename: match ? match[1] : null,
    reportId: idHeader ? Number(idHeader) : null,
    summary,
  };
}

export const api = {
  summary: () => jsonFetch<Summary>("/summary"),
  stuckRuns: () => jsonFetch<{ stuck: StuckRun[] }>("/stuck-runs").then((r) => r.stuck),
  dags: () => jsonFetch<{ dags: DAG[] }>("/dags").then((r) => r.dags),
  runs: (dagId: string, range: string = "all") =>
    jsonFetch<{ runs: DAGRun[]; range: string; total: number }>(
      `/runs/${dagId}?range=${encodeURIComponent(range)}`,
    ).then((r) => r.runs),
  tasks: (dagId: string, runId: string) =>
    jsonFetch<{ tasks: TaskInstance[] }>(
      `/tasks/${dagId}/${encodeURIComponent(runId)}`,
    ).then((r) => r.tasks),
  taskLogs: (dagId: string, runId: string, taskId: string, attempt = 1) =>
    jsonFetch<TaskLogs>(
      `/tasks/${dagId}/${encodeURIComponent(runId)}/${taskId}/logs?attempt=${attempt}`,
    ),
  resync: (dagId: string, runId: string) =>
    jsonFetch<{ resynced: boolean; state?: string; reason?: string }>(
      `/runs/${dagId}/${encodeURIComponent(runId)}/resync`,
      { method: "POST" },
    ),
  triggerRun: (dagId: string) =>
    jsonFetch<{ triggered: boolean; run_id?: string; state?: string }>(
      `/dags/${dagId}/trigger`,
      { method: "POST" },
    ),
  runDiff: (
    dagId: string,
    runId: string,
    baseline?: { dagId: string; runId: string },
  ) => {
    const qs = baseline
      ? `?baseline_dag_id=${encodeURIComponent(baseline.dagId)}&baseline_run_id=${encodeURIComponent(baseline.runId)}`
      : "";
    return jsonFetch<RunDiff>(
      `/runs/${dagId}/${encodeURIComponent(runId)}/diff${qs}`,
    );
  },
  analytics: (range: "7d" | "30d" = "7d") =>
    jsonFetch<AnalyticsResponse>(`/analytics?range=${range}`),
  alertConfigs: () =>
    jsonFetch<{ configs: AlertConfig[] }>("/alerts/config").then((r) => r.configs),
  updateAlertConfig: (dagId: string, body: Omit<AlertConfig, "dag_id">) =>
    jsonFetch<AlertConfig>(`/alerts/config/${dagId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  slaConfigs: () =>
    jsonFetch<{ configs: SlaConfig[] }>("/sla/configs").then((r) => r.configs),
  updateSlaConfig: (dagId: string, body: Omit<SlaConfig, "dag_id">) =>
    jsonFetch<SlaConfig>(`/sla/configs/${dagId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  slaAtRisk: () =>
    jsonFetch<{ at_risk: SlaAtRisk[] }>("/sla/at-risk").then((r) => r.at_risk),
  slaBreaches: (range: "24h" | "7d" | "30d" = "7d") =>
    jsonFetch<{ breaches: SlaBreach[] }>(`/sla/breaches?range=${range}`).then((r) => r.breaches),
  explain: (dagId: string, runId: string) =>
    jsonFetch<{ insight: string }>(
      `/ai/explain/${dagId}/${encodeURIComponent(runId)}`,
    ),
  stakeholder: (dagId: string) =>
    jsonFetch<{ summary: string }>(`/ai/stakeholder/${dagId}`),
  notifications: () =>
    jsonFetch<{
      configured: boolean;
      notifications: Array<{
        id: number;
        dag_id: string;
        run_id: string;
        event: string;
        delivered: string;
        created_at: string | null;
      }>;
    }>("/notifications"),
  testNotification: () =>
    jsonFetch<{ delivered: string }>("/notifications/test", { method: "POST" }),
  generateReport: (range: ReportRange, format: ReportFormat) =>
    blobFetch(`/reports?range=${range}&format=${format}`),
  reportHistory: () =>
    jsonFetch<{ reports: ReportHistoryItem[] }>("/reports/history").then((r) => r.reports),
  downloadStoredReport: (id: number, format: ReportFormat) =>
    blobFetch(`/reports/history/${id}?format=${format}`),
  getReportSchedule: () => jsonFetch<ReportSchedule>("/reports/schedule"),
  updateReportSchedule: (body: Omit<ReportSchedule, "last_sent_at" | "global_webhook_configured">) =>
    jsonFetch<ReportSchedule>("/reports/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAnnotation: (dagId: string, runId: string) =>
    jsonFetch<RunAnnotation>(`/annotations/${dagId}/${encodeURIComponent(runId)}`),
  upsertAnnotation: (dagId: string, runId: string, note: string) =>
    jsonFetch<RunAnnotation>(`/annotations/${dagId}/${encodeURIComponent(runId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),
  listAnnotations: (dagId?: string) =>
    jsonFetch<{ annotations: RunAnnotation[] }>(
      dagId ? `/annotations?dag_id=${encodeURIComponent(dagId)}` : "/annotations",
    ).then((r) => r.annotations),
  getSettings: () => jsonFetch<Settings>("/settings"),
  updateSettings: (body: SettingsUpdate) =>
    jsonFetch<Settings>("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  dangerResetAlertConfigs: () =>
    jsonFetch<{ deleted: number }>("/settings/danger/reset-alert-configs", { method: "POST" }),
  dangerClearNotifications: () =>
    jsonFetch<{ deleted: number }>("/settings/danger/clear-notifications", { method: "POST" }),
  dangerClearReports: () =>
    jsonFetch<{ deleted: number }>("/settings/danger/clear-reports", { method: "POST" }),
  dangerFullResync: () =>
    jsonFetch<{ runs_deleted: number; tasks_deleted: number; runs_pulled: number }>(
      "/settings/danger/full-resync",
      { method: "POST" },
    ),
  listEnvironments: () =>
    jsonFetch<{ environments: EnvironmentInfo[] }>("/environments").then((r) => r.environments),
  createEnvironment: (body: EnvironmentCreate) =>
    jsonFetch<EnvironmentInfo>("/environments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateEnvironment: (id: number, body: EnvironmentUpdate) =>
    jsonFetch<EnvironmentInfo>(`/environments/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteEnvironment: (id: number) =>
    jsonFetch<{ deleted: boolean; id: number }>(`/environments/${id}`, { method: "DELETE" }),
  testEnvironment: (id: number) =>
    jsonFetch<{ ok: boolean; latency_ms: number; error?: string }>(
      `/environments/${id}/test`,
      { method: "POST" },
    ),
  // Auth — session-cookie-based.
  authMe: () => jsonFetch<CurrentUser>("/auth/me"),
  authLogin: (email: string, password: string) =>
    jsonFetch<CurrentUser>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  authSignup: (email: string, password: string, name?: string) =>
    jsonFetch<CurrentUser>("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name: name || null }),
    }),
  authLogout: () =>
    jsonFetch<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  // API tokens — for curl / scripts. Plaintext only ever returned by createApiToken.
  listApiTokens: () =>
    jsonFetch<{ tokens: ApiTokenInfo[] }>("/api-tokens").then((r) => r.tokens),
  createApiToken: (name: string) =>
    jsonFetch<NewApiToken>("/api-tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  revokeApiToken: (id: number) =>
    jsonFetch<{ revoked: boolean; id: number }>(`/api-tokens/${id}`, { method: "DELETE" }),
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
