"use client";

import { useEffect, useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { api, type DAG, type DAGRun, type StuckRun, type Summary } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/utils";
import { Sidebar } from "@/components/sidebar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Metric } from "@/components/metric";
import { StatusPill } from "@/components/status-pill";
import { RunChart } from "@/components/run-chart";
import { AIPanel } from "@/components/ai-panel";
import { TaskPanel } from "@/components/task-panel";
import { NotificationsPanel } from "@/components/notifications-panel";
import { StuckRunsBanner } from "@/components/stuck-runs-banner";
import { DiffPanel } from "@/components/diff-panel";

export function Dashboard() {
  const [dags, setDags] = useState<DAG[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [stuck, setStuck] = useState<StuckRun[]>([]);
  const [runs, setRuns] = useState<DAGRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [range, setRange] = useState<"24h" | "7d" | "30d" | "all">("all");
  const [page, setPage] = useState(0);
  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const PAGE_SIZE = 10;

  const loadGlobal = async () => {
    try {
      const [s, d, st] = await Promise.all([
        api.summary(),
        api.dags(),
        api.stuckRuns().catch(() => []),
      ]);
      setSummary(s);
      setDags(d);
      setStuck(st);
      if (!selected && d.length > 0) setSelected(d[0].dag_id);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to reach backend");
    }
  };

  const loadRuns = async (dagId: string, r: typeof range = range) => {
    try {
      const fetched = await api.runs(dagId, r);
      setRuns(fetched);
      setPage(0);
      const firstFailed = fetched.find((x) => x.state === "failed");
      setSelectedRun(firstFailed?.run_id ?? fetched[0]?.run_id ?? null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load runs");
    }
  };

  useEffect(() => {
    loadGlobal();
  }, []);

  useEffect(() => {
    if (selected) loadRuns(selected, range);
  }, [selected, range]);

  const refresh = async () => {
    setRefreshing(true);
    await loadGlobal();
    if (selected) await loadRuns(selected, range);
    setRefreshing(false);
  };

  const triggerRun = async () => {
    if (!selected) return;
    setTriggering(true);
    setTriggerMsg(null);
    try {
      const res = await api.triggerRun(selected);
      setTriggerMsg(`Triggered · ${res.state ?? "queued"}`);
      setTimeout(() => setTriggerMsg(null), 4000);
    } catch (e) {
      setTriggerMsg(e instanceof Error ? e.message : "Trigger failed");
      setTimeout(() => setTriggerMsg(null), 6000);
    } finally {
      setTriggering(false);
    }
  };

  const dagFailed = runs.filter((r) => r.state === "failed").length;
  const dagSuccessRate =
    runs.length > 0 ? Math.round(((runs.length - dagFailed) / runs.length) * 1000) / 10 : 0;
  const totalPages = Math.max(1, Math.ceil(runs.length / PAGE_SIZE));
  const pagedRuns = runs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const RANGE_OPTIONS: { value: typeof range; label: string }[] = [
    { value: "24h", label: "24h" },
    { value: "7d", label: "7d" },
    { value: "30d", label: "30d" },
    { value: "all", label: "All" },
  ];

  if (loadError && dags.length === 0) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="max-w-md space-y-2 text-center">
          <h1 className="text-lg font-semibold">Backend unreachable</h1>
          <p className="text-sm text-muted-foreground">{loadError}</p>
          <p className="text-xs text-muted-foreground">
            Set <code className="font-mono">NEXT_PUBLIC_API_URL</code> if your backend isn&apos;t at
            localhost:8000.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar dags={dags} selected={selected} onSelect={setSelected} />

      <main className="flex-1 overflow-y-auto scrollbar-thin">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/80 px-6 backdrop-blur">
          <div>
            <h1 className="font-mono text-sm">{selected ?? "—"}</h1>
            <p className="text-[11px] text-muted-foreground">
              {runs.length > 0
                ? `Last run ${formatRelativeTime(runs[0].start_date)}`
                : "No runs"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {triggerMsg && (
              <span className="text-[11px] text-muted-foreground">{triggerMsg}</span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={triggerRun}
              disabled={!selected || triggering}
            >
              <Play className={`h-3.5 w-3.5 ${triggering ? "animate-pulse" : ""}`} />
              Trigger run
            </Button>
            <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </header>

        <div className="space-y-6 p-6">
          <StuckRunsBanner
            stuck={stuck}
            onSelect={(dagId, runId) => {
              setSelected(dagId);
              setSelectedRun(runId);
            }}
          />

          {summary && (
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Metric label="Total runs" value={summary.total_runs} />
              <Metric
                label="Success rate"
                value={`${summary.success_rate}%`}
                tone={summary.success_rate >= 90 ? "success" : summary.success_rate >= 70 ? "warning" : "danger"}
                hint="Across all DAGs"
              />
              <Metric label="Failed" value={summary.failed} tone={summary.failed > 0 ? "danger" : "default"} />
              <Metric label="Running" value={summary.running} tone={summary.running > 0 ? "warning" : "default"} />
            </section>
          )}

          {selected && (
            <>
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <div>
                    <CardTitle>Run duration</CardTitle>
                    <p className="text-xs text-muted-foreground">
                      {runs.length} runs · {dagSuccessRate}% success
                    </p>
                  </div>
                  <div className="flex gap-1 rounded-md border p-0.5">
                    {RANGE_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => setRange(opt.value)}
                        className={`rounded px-2.5 py-1 text-xs transition-colors ${
                          range === opt.value
                            ? "bg-accent text-accent-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </CardHeader>
                <CardContent>
                  <RunChart runs={runs} />
                </CardContent>
              </Card>

              <div className="grid gap-6 lg:grid-cols-3">
                <Card className="lg:col-span-2">
                  <CardHeader>
                    <CardTitle>Runs</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                          <th className="px-5 py-2 font-medium">Run</th>
                          <th className="px-5 py-2 font-medium">State</th>
                          <th className="px-5 py-2 font-medium">Duration</th>
                          <th className="px-5 py-2 font-medium">Started</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedRuns.map((r) => (
                          <tr
                            key={r.run_id}
                            onClick={() => setSelectedRun(r.run_id)}
                            className={`cursor-pointer border-b border-border/50 transition-colors hover:bg-accent/40 ${
                              selectedRun === r.run_id ? "bg-accent/40" : ""
                            }`}
                          >
                            <td className="px-5 py-2.5 font-mono text-xs text-muted-foreground">
                              {r.run_id.length > 36 ? `${r.run_id.slice(0, 36)}…` : r.run_id}
                            </td>
                            <td className="px-5 py-2.5">
                              <StatusPill state={r.state} />
                            </td>
                            <td className="px-5 py-2.5 tabular-nums text-muted-foreground">
                              {formatDuration(r.duration_seconds)}
                            </td>
                            <td className="px-5 py-2.5 text-muted-foreground">
                              {formatRelativeTime(r.start_date)}
                            </td>
                          </tr>
                        ))}
                        {pagedRuns.length === 0 && (
                          <tr>
                            <td colSpan={4} className="px-5 py-8 text-center text-muted-foreground">
                              No runs in this range
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                    {runs.length > PAGE_SIZE && (
                      <div className="flex items-center justify-between border-t px-5 py-2 text-xs text-muted-foreground">
                        <span>
                          {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, runs.length)} of{" "}
                          {runs.length}
                        </span>
                        <div className="flex gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPage((p) => Math.max(0, p - 1))}
                            disabled={page === 0}
                          >
                            Prev
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                            disabled={page >= totalPages - 1}
                          >
                            Next
                          </Button>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>

                <div className="space-y-6">
                  <Card>
                    <CardHeader>
                      <CardTitle>Failure analysis</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        {selectedRun
                          ? "AI explains the selected run"
                          : "Select a run to analyze"}
                      </p>
                    </CardHeader>
                    <CardContent>
                      <AIPanel
                        mode="explain"
                        dagId={selected}
                        runId={selectedRun ?? undefined}
                        label="Analyze with AI"
                      />
                    </CardContent>
                  </Card>

                  {selectedRun &&
                    runs.find((r) => r.run_id === selectedRun)?.state === "failed" && (
                      <Card>
                        <CardHeader>
                          <CardTitle>What changed?</CardTitle>
                          <p className="text-xs text-muted-foreground">
                            Diff against last successful run
                          </p>
                        </CardHeader>
                        <CardContent>
                          <DiffPanel dagId={selected} runId={selectedRun} />
                        </CardContent>
                      </Card>
                    )}

                  <Card>
                    <CardHeader>
                      <CardTitle>Stakeholder summary</CardTitle>
                      <p className="text-xs text-muted-foreground">Plain-English status</p>
                    </CardHeader>
                    <CardContent>
                      <AIPanel mode="stakeholder" dagId={selected} label="Generate summary" />
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle>Alerts</CardTitle>
                      <p className="text-xs text-muted-foreground">Failure notifications</p>
                    </CardHeader>
                    <CardContent>
                      <NotificationsPanel />
                    </CardContent>
                  </Card>
                </div>
              </div>

              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <div>
                    <CardTitle>Tasks in selected run</CardTitle>
                    <p className="text-xs text-muted-foreground">
                      {selectedRun
                        ? "Click a task to see error and logs"
                        : "Select a run from the table above"}
                    </p>
                  </div>
                  {selectedRun && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={async () => {
                        await api.resync(selected, selectedRun);
                        await loadRuns(selected);
                      }}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Resync run
                    </Button>
                  )}
                </CardHeader>
                <CardContent className="p-0">
                  <TaskPanel dagId={selected} runId={selectedRun} />
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
