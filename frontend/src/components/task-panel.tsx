"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Loader2 } from "lucide-react";
import { api, type TaskInstance } from "@/lib/api";
import { formatDuration, cn } from "@/lib/utils";
import { StatusPill } from "@/components/status-pill";

type Props = {
  dagId: string;
  runId: string | null;
};

export function TaskPanel({ dagId, runId }: Props) {
  const [tasks, setTasks] = useState<TaskInstance[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      setTasks([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .tasks(dagId, runId)
      .then((t) => {
        if (cancelled) return;
        setTasks(t);
        const failed = t.find((x) => x.state === "failed");
        setExpanded(failed?.task_id ?? null);
      })
      .catch(() => setTasks([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dagId, runId]);

  if (!runId) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        Select a run to see its tasks
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading tasks…
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">No tasks found</div>
    );
  }

  return (
    <div className="divide-y">
      {tasks.map((t) => (
        <TaskRow
          key={t.task_id}
          task={t}
          dagId={dagId}
          runId={runId}
          expanded={expanded === t.task_id}
          onToggle={() => setExpanded(expanded === t.task_id ? null : t.task_id)}
        />
      ))}
    </div>
  );
}

function TaskRow({
  task,
  dagId,
  runId,
  expanded,
  onToggle,
}: {
  task: TaskInstance;
  dagId: string;
  runId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const canExpand = task.state === "failed" || task.try_number != null;

  return (
    <div>
      <button
        onClick={canExpand ? onToggle : undefined}
        className={cn(
          "flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm",
          canExpand && "hover:bg-accent/40",
        )}
        disabled={!canExpand}
      >
        {canExpand ? (
          expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          )
        ) : (
          <span className="w-3.5" />
        )}
        <span className="flex-1 truncate font-mono text-xs">{task.task_id}</span>
        <StatusPill state={task.state} />
        <span className="w-16 text-right tabular-nums text-xs text-muted-foreground">
          {formatDuration(task.duration_seconds)}
        </span>
      </button>

      {expanded && (
        <ExpandedTask
          task={task}
          dagId={dagId}
          runId={runId}
        />
      )}
    </div>
  );
}

function ExpandedTask({
  task,
  dagId,
  runId,
}: {
  task: TaskInstance;
  dagId: string;
  runId: string;
}) {
  const [logs, setLogs] = useState<string | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);

  const loadLogs = async () => {
    setLogsLoading(true);
    setLogsError(null);
    try {
      const r = await api.taskLogs(dagId, runId, task.task_id, task.try_number ?? 1);
      setLogs(r.empty ? "(no logs)" : r.logs);
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : "Failed to load logs");
    } finally {
      setLogsLoading(false);
    }
  };

  return (
    <div className="space-y-3 bg-muted/20 px-5 py-3 text-xs">
      {task.error_message && (
        <div>
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Error
          </div>
          <pre className="max-h-48 overflow-auto scrollbar-thin whitespace-pre-wrap rounded border bg-background p-3 font-mono leading-relaxed">
            {task.error_message}
          </pre>
        </div>
      )}

      <div>
        {!logs && !logsLoading && (
          <button
            onClick={loadLogs}
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <FileText className="h-3 w-3" />
            View full logs (attempt {task.try_number ?? 1})
          </button>
        )}
        {logsLoading && (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading logs…
          </div>
        )}
        {logsError && <div className="text-danger">{logsError}</div>}
        {logs && (
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Full logs
              </span>
              <button
                onClick={() => setLogs(null)}
                className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
              >
                hide
              </button>
            </div>
            <pre className="max-h-96 overflow-auto scrollbar-thin whitespace-pre-wrap rounded border bg-background p-3 font-mono leading-relaxed">
              {logs}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
