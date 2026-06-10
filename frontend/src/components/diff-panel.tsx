"use client";

import { useEffect, useState } from "react";
import { GitCompare } from "lucide-react";
import { api, type RunDiff } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/utils";
import { StatusPill } from "@/components/status-pill";
import { EmptyState } from "@/components/empty-state";

type Props = {
  dagId: string;
  runId: string;
};

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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDiff(null);
    api
      .runDiff(dagId, runId)
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
  }, [dagId, runId]);

  if (loading) {
    return (
      <div className="space-y-2">
        <div className="h-3 w-3/4 rounded shimmer" />
        <div className="h-9 rounded shimmer" />
        <div className="h-9 rounded shimmer" />
      </div>
    );
  }
  if (error) return <p className="text-xs text-danger">{error}</p>;
  if (!diff) return null;

  if (!diff.baseline) {
    return (
      <EmptyState
        icon={GitCompare}
        title="Nothing to diff"
        hint="No prior successful run for this DAG."
      />
    );
  }

  const hasChanges =
    diff.task_changes.length > 0 ||
    diff.added_tasks.length > 0 ||
    diff.removed_tasks.length > 0;

  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-start gap-2 text-xs text-muted-foreground">
        <GitCompare className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="flex-1">
          Compared to last success ({formatRelativeTime(diff.baseline.start_date)})
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
        <p className="text-xs text-muted-foreground">
          No task-level changes from the last successful run.
        </p>
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
    </div>
  );
}
