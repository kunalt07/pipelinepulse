export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AUTH_USER = process.env.NEXT_PUBLIC_AUTH_USER ?? "";
const AUTH_PASS = process.env.NEXT_PUBLIC_AUTH_PASS ?? "";

function authHeaders(): Record<string, string> {
  if (!AUTH_USER || !AUTH_PASS) return {};
  if (typeof window === "undefined") return {};
  const token = window.btoa(`${AUTH_USER}:${AUTH_PASS}`);
  return { Authorization: `Basic ${token}` };
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

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = { ...authHeaders(), ...(init?.headers ?? {}) };
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  if (res.status === 401) throw new Error("Unauthorized — check AUTH_USER/AUTH_PASS");
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
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
};
