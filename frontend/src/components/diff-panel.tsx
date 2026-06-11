"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, GitCompare, Loader2 } from "lucide-react";
import { api, type DAG, type DAGRun, type RunDiff } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/utils";
import { StatusPill } from "@/components/status-pill";
import { EmptyState } from "@/components/empty-state";

type Props = {
  dagId: string;
  runId: string;
};

type BaselineSpec = { dagId: string; runId: string } | null; // null = default last-success

function formatDelta(seconds: number | null): string {
  if (seconds == null) return "—";
  const sign = seconds > 0 ? "+" : "";
  return `${sign}${formatDuration(Math.abs(seconds))}`.replace(
    /^\+(\d)/,
    (m) => (seconds > 0 ? `+${m.slice(1)}` : m),
  );
}

export function DiffPanel({ dagId, runId }: Props) {
  const [diff, setDiff] = useState<RunDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<BaselineSpec>(null);

  // Reset baseline override when the current run changes
  useEffect(() => {
    setBaseline(null);
  }, [dagId, runId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDiff(null);
    api
      .runDiff(dagId, runId, baseline ?? undefined)
      .then((d) => {
        if (!cancelled) setDiff(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load diff");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dagId, runId, baseline]);

  return (
    <div className="space-y-3 text-sm">
      <BaselinePicker
        currentDagId={dagId}
        currentRunId={runId}
        baseline={baseline}
        onChange={setBaseline}
      />

      {loading && (
        <div className="space-y-2">
          <div className="h-3 w-3/4 rounded shimmer" />
          <div className="h-9 rounded shimmer" />
          <div className="h-9 rounded shimmer" />
        </div>
      )}

      {error && <p className="text-xs text-danger">{error}</p>}

      {!loading && !error && diff && <DiffBody diff={diff} explicit={!!baseline} />}
    </div>
  );
}

function DiffBody({ diff, explicit }: { diff: RunDiff; explicit: boolean }) {
  if (!diff.baseline) {
    return (
      <EmptyState
        icon={GitCompare}
        title="Nothing to diff"
        hint={
          explicit
            ? "Selected baseline could not be loaded."
            : "No prior successful run for this DAG. Pick a baseline above to compare against any other run."
        }
      />
    );
  }

  const hasChanges =
    diff.task_changes.length > 0 ||
    diff.added_tasks.length > 0 ||
    diff.removed_tasks.length > 0;

  const baselineLabel = diff.baseline.dag_id
    ? `${diff.baseline.dag_id} · ${formatRelativeTime(diff.baseline.start_date)}`
    : formatRelativeTime(diff.baseline.start_date);

  return (
    <>
      <div className="flex items-start gap-2 text-xs text-muted-foreground">
        <GitCompare className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="flex-1">
          Compared to {explicit ? "selected run" : "last success"} ({baselineLabel})
          {diff.duration_delta_seconds != null && (
            <span className="ml-1">
              · run duration{" "}
              <span
                className={
                  diff.duration_delta_seconds > 0
                    ? "text-amber-500"
                    : "text-emerald-500"
                }
              >
                {formatDelta(diff.duration_delta_seconds)}
              </span>
            </span>
          )}
        </div>
      </div>

      {!hasChanges && (
        <p className="text-xs text-muted-foreground">No task-level differences.</p>
      )}

      {diff.task_changes.length > 0 && (
        <ul className="space-y-1.5">
          {diff.task_changes.map((c) => (
            <li
              key={c.task_id}
              className="flex items-center justify-between gap-3 rounded border border-border/50 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">{c.task_id}</div>
                {c.state_changed && (
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px]">
                    <StatusPill state={c.baseline_state} />
                    <span className="text-muted-foreground">→</span>
                    <StatusPill state={c.current_state} />
                  </div>
                )}
              </div>
              {c.duration_delta_seconds != null && (
                <span
                  className={`shrink-0 tabular-nums text-xs font-semibold ${
                    c.duration_delta_seconds > 0
                      ? "text-amber-500"
                      : "text-emerald-500"
                  }`}
                >
                  {formatDelta(c.duration_delta_seconds)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {(diff.added_tasks.length > 0 || diff.removed_tasks.length > 0) && (
        <div className="space-y-1 text-xs text-muted-foreground">
          {diff.added_tasks.length > 0 && (
            <div>
              <span className="text-emerald-500">+ added:</span>{" "}
              <span className="font-mono">{diff.added_tasks.join(", ")}</span>
            </div>
          )}
          {diff.removed_tasks.length > 0 && (
            <div>
              <span className="text-destructive">− removed:</span>{" "}
              <span className="font-mono">{diff.removed_tasks.join(", ")}</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function BaselinePicker({
  currentDagId,
  currentRunId,
  baseline,
  onChange,
}: {
  currentDagId: string;
  currentRunId: string;
  baseline: BaselineSpec;
  onChange: (b: BaselineSpec) => void;
}) {
  const [open, setOpen] = useState(false);
  const [allDags, setAllDags] = useState<DAG[]>([]);
  const [pickerDag, setPickerDag] = useState(currentDagId);
  const [runs, setRuns] = useState<DAGRun[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Reset picker DAG to current DAG when current changes
  useEffect(() => {
    setPickerDag(currentDagId);
  }, [currentDagId, currentRunId]);

  // Click-outside to close
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // Lazy-fetch DAGs the first time the popover opens
  useEffect(() => {
    if (!open || allDags.length > 0) return;
    api.dags().then(setAllDags).catch(() => setAllDags([]));
  }, [open, allDags.length]);

  // Fetch runs for the selected picker DAG
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setRunsLoading(true);
    setRuns(null);
    api
      .runs(pickerDag, "30d")
      .then((r) => {
        if (!cancelled) setRuns(r);
      })
      .catch(() => {
        if (!cancelled) setRuns([]);
      })
      .finally(() => {
        if (!cancelled) setRunsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pickerDag, open]);

  const eligibleRuns = useMemo(() => {
    if (!runs) return [];
    return runs.filter((r) => !(pickerDag === currentDagId && r.run_id === currentRunId));
  }, [runs, pickerDag, currentDagId, currentRunId]);

  const previousRun = eligibleRuns[0];

  const summary = baseline
    ? baseline.dagId === currentDagId
      ? "Custom baseline"
      : `${baseline.dagId} · custom`
    : "Last success";

  return (
    <div className="relative" ref={popoverRef}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[11px] font-semibold text-foreground hover:bg-accent"
        >
          <GitCompare className="h-3 w-3" />
          Baseline: {summary}
          <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {baseline && (
          <button
            onClick={() => onChange(null)}
            className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
          >
            Reset to last success
          </button>
        )}
      </div>

      {open && (
        <div className="absolute left-0 top-full z-20 mt-1.5 w-[420px] max-w-[calc(100vw-3rem)] rounded-md border border-border bg-card p-3 shadow-lg">
          <div className="space-y-2.5">
            <div className="flex flex-wrap gap-1">
              <button
                onClick={() => {
                  onChange(null);
                  setOpen(false);
                }}
                className="rounded border border-border bg-background px-2 py-1 text-[11px] font-semibold hover:bg-accent"
              >
                Last success
              </button>
              <button
                disabled={!previousRun}
                onClick={() => {
                  if (previousRun) {
                    onChange({ dagId: pickerDag, runId: previousRun.run_id });
                    setOpen(false);
                  }
                }}
                className="rounded border border-border bg-background px-2 py-1 text-[11px] font-semibold hover:bg-accent disabled:opacity-40"
              >
                Previous run
              </button>
            </div>

            <div className="space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                DAG
              </div>
              <select
                value={pickerDag}
                onChange={(e) => setPickerDag(e.target.value)}
                className="h-7 w-full rounded border border-border bg-background px-2 font-mono text-[11px]"
              >
                {/* Always include the current DAG even if /dags hasn't loaded yet */}
                {allDags.length === 0 && <option value={currentDagId}>{currentDagId}</option>}
                {allDags.map((d) => (
                  <option key={d.dag_id} value={d.dag_id}>
                    {d.dag_id}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  Run
                </div>
                {runsLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
              </div>
              <div className="max-h-56 overflow-y-auto rounded border border-border bg-background scrollbar-thin">
                {!runsLoading && eligibleRuns.length === 0 && (
                  <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
                    No comparable runs.
                  </p>
                )}
                {eligibleRuns.map((r) => (
                  <button
                    key={r.run_id}
                    onClick={() => {
                      onChange({ dagId: pickerDag, runId: r.run_id });
                      setOpen(false);
                    }}
                    className="flex w-full items-center justify-between gap-2 border-b border-border/40 px-2 py-1.5 text-left text-[11px] last:border-b-0 hover:bg-accent/50"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <StatusPill state={r.state} />
                      <span className="truncate font-mono">
                        {r.run_id.length > 32 ? `${r.run_id.slice(0, 32)}…` : r.run_id}
                      </span>
                    </div>
                    <span className="shrink-0 text-muted-foreground">
                      {formatRelativeTime(r.start_date)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
