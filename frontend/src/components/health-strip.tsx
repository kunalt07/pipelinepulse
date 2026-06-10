"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api, type DAG, type DAGRun } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/utils";

type Props = {
  dags: DAG[];
  selected: string | null;
  onSelect: (dagId: string, runId?: string) => void;
};

type DagHistory = {
  dag_id: string;
  runs: DAGRun[];
};

const STATE_BG: Record<string, string> = {
  success: "bg-success",
  failed: "bg-danger",
  running: "bg-blue-500",
  queued: "bg-muted-foreground/40",
};

export function HealthStrip({ dags, selected, onSelect }: Props) {
  const [histories, setHistories] = useState<DagHistory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (dags.length === 0) {
      setHistories([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(
      dags.map(async (d) => ({
        dag_id: d.dag_id,
        runs: await api.runs(d.dag_id, "24h").catch(() => []),
      })),
    )
      .then((res) => {
        if (!cancelled) setHistories(res);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dags]);

  if (loading) {
    return (
      <div className="space-y-2 rounded-lg border border-border bg-card p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
            Last 24 hours
          </div>
        </div>
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-2.5 w-32 shrink-0 rounded shimmer" />
              <div className="h-4 flex-1 rounded shimmer" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (histories.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-lg border border-border bg-card p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Last 24 hours
        </div>
        <div className="flex items-center gap-3 text-[11px] font-medium text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-success" /> success
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-danger" /> failed
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-blue-500" /> running
          </span>
        </div>
      </div>
      <div className="space-y-1.5">
        {histories.map((h) => {
          const ordered = [...h.runs].reverse();
          const failedCount = h.runs.filter((r) => r.state === "failed").length;
          return (
            <div
              key={h.dag_id}
              onClick={() => onSelect(h.dag_id)}
              className={`group flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-accent/40 ${
                selected === h.dag_id ? "bg-accent/40" : ""
              }`}
            >
              <div className="w-32 shrink-0 truncate font-mono text-[11px] font-semibold text-foreground/90">{h.dag_id}</div>
              <div className="flex h-5 flex-1 items-stretch gap-[2px]">
                {ordered.length === 0 ? (
                  <div className="flex flex-1 items-center text-[10px] text-muted-foreground/60">
                    no runs
                  </div>
                ) : (
                  ordered.map((r) => (
                    <button
                      key={r.run_id}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelect(h.dag_id, r.run_id);
                      }}
                      title={`${r.state} · ${formatDuration(r.duration_seconds)} · ${formatRelativeTime(r.start_date)}`}
                      className={`flex-1 rounded-sm transition-opacity hover:opacity-80 ${
                        STATE_BG[r.state] ?? STATE_BG.queued
                      } ${r.state === "running" ? "animate-pulse" : ""}`}
                    />
                  ))
                )}
              </div>
              <div className="w-12 shrink-0 text-right tabular-nums text-[11px] font-semibold text-muted-foreground">
                {h.runs.length} run{h.runs.length === 1 ? "" : "s"}
              </div>
              <div
                className={`w-12 shrink-0 text-right tabular-nums text-[11px] font-semibold ${
                  failedCount > 0 ? "text-danger" : "text-muted-foreground/60"
                }`}
              >
                {failedCount > 0 ? `${failedCount} fail` : "ok"}
              </div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}
