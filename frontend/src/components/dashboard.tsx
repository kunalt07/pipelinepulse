"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Inbox, Play, RefreshCw, StickyNote } from "lucide-react";
import { api, type DAG, type DAGRun, type StuckRun, type Summary } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/utils";
import { Sidebar, type View } from "@/components/sidebar";
import { AnalyticsView } from "@/components/analytics-view";
import { ReportsView } from "@/components/reports-view";
import { SettingsView } from "@/components/settings-view";
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
import { AnnotationPanel } from "@/components/annotation-panel";
import { HealthStrip } from "@/components/health-strip";
import { EmptyState } from "@/components/empty-state";
import { AlertConfigPanel } from "@/components/alert-config-panel";

const cardEntry = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const },
};

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
  const [view, setView] = useState<View>("dashboard");
  const [annotated, setAnnotated] = useState<Set<string>>(new Set());

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
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const v = params.get("view");
      if (v === "reports" || v === "analytics" || v === "settings" || v === "dashboard") {
        setView(v);
      }
    }
  }, []);

  useEffect(() => {
    if (selected) loadRuns(selected, range);
  }, [selected, range]);

  useEffect(() => {
    if (!selected) {
      setAnnotated(new Set());
      return;
    }
    let cancelled = false;
    api
      .listAnnotations(selected)
      .then((items) => {
        if (cancelled) return;
        setAnnotated(new Set(items.map((a) => a.run_id)));
      })
      .catch(() => {
        if (!cancelled) setAnnotated(new Set());
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const onAnnotationChange = useCallback(
    (runId: string) => (hasNote: boolean) => {
      setAnnotated((prev) => {
        const next = new Set(prev);
        if (hasNote) next.add(runId);
        else next.delete(runId);
        return next;
      });
    },
    [],
  );

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

  // Build sparkline data for global metrics from the per-DAG runs we have loaded.
  // For "Total runs" sparkline we use the count over recent buckets; for the others we
  // chart the raw recent values reversed (oldest → newest).
  const sparkSeries = (() => {
    const ordered = [...runs].reverse(); // oldest → newest
    if (ordered.length === 0) return { duration: [] as number[], success: [] as number[] };
    const duration = ordered
      .map((r) => r.duration_seconds ?? 0)
      .slice(-20);
    // rolling success-rate over a window of 5 runs
    const window = 5;
    const success: number[] = [];
    for (let i = 0; i < ordered.length; i++) {
      const slice = ordered.slice(Math.max(0, i - window + 1), i + 1);
      const ok = slice.filter((r) => r.state === "success").length;
      success.push((ok / slice.length) * 100);
    }
    return { duration, success: success.slice(-20) };
  })();

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

  const successTone =
    summary && summary.success_rate >= 90
      ? "success"
      : summary && summary.success_rate >= 70
        ? "warning"
        : "danger";

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        dags={dags}
        selected={selected}
        onSelect={(d) => {
          setSelected(d);
          setView("dashboard");
        }}
        view={view}
        onChangeView={setView}
      />

      <main className="flex-1 overflow-y-auto scrollbar-thin">
        {view === "analytics" && <AnalyticsView />}
        {view === "reports" && <ReportsView />}
        {view === "settings" && <SettingsView />}
        {view === "dashboard" && (
        <>
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/80 px-6 backdrop-blur">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-muted-foreground">Dashboard</span>
            <span className="text-xs text-muted-foreground/50">/</span>
            <div>
              <h1 className="font-mono text-sm font-bold text-foreground">{selected ?? "—"}</h1>
              <p className="text-[11px] font-medium text-muted-foreground">
                {runs.length > 0
                  ? `Last run ${formatRelativeTime(runs[0].start_date)}`
                  : "No runs"}
              </p>
            </div>
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

          <HealthStrip
            dags={dags}
            selected={selected}
            onSelect={(dagId, runId) => {
              setSelected(dagId);
              if (runId) setSelectedRun(runId);
            }}
          />

          {summary && (
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Metric
                label="Total runs"
                value={summary.total_runs}
                tone="brand"
                hint="All DAGs"
                delay={0.05}
              />
              <Metric
                label="Success rate"
                value={summary.success_rate}
                decimals={1}
                suffix="%"
                tone={successTone}
                hint={sparkSeries.success.length > 1 ? "Selected DAG · last 20" : "All DAGs"}
                spark={sparkSeries.success.length > 1 ? sparkSeries.success : undefined}
                delay={0.1}
              />
              <Metric
                label="Failed"
                value={summary.failed}
                tone={summary.failed > 0 ? "danger" : "default"}
                hint="All DAGs"
                delay={0.15}
              />
              <Metric
                label="Running"
                value={summary.running}
                tone={summary.running > 0 ? "warning" : "default"}
                hint="All DAGs"
                delay={0.2}
              />
            </section>
          )}

          {selected && (
            <>
              <motion.div {...cardEntry}>
                <Card>
                  <CardHeader className="flex-row items-center justify-between">
                    <div>
                      <CardTitle>Run duration</CardTitle>
                      <p className="text-xs font-medium text-muted-foreground">
                        {runs.length} runs · {dagSuccessRate}% success
                      </p>
                    </div>
                    <div className="flex gap-1 rounded-md border border-border/60 bg-background/50 p-0.5">
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
              </motion.div>

              <div className="grid gap-6 lg:grid-cols-3">
                <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.05 }} className="lg:col-span-2">
                  <Card>
                    <CardHeader>
                      <CardTitle>Runs</CardTitle>
                    </CardHeader>
                    <CardContent className="p-0">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border text-left text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                            <th className="px-5 py-2.5">Run</th>
                            <th className="px-5 py-2.5">State</th>
                            <th className="px-5 py-2.5">Duration</th>
                            <th className="px-5 py-2.5">Started</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pagedRuns.map((r) => (
                            <tr
                              key={r.run_id}
                              onClick={() => setSelectedRun(r.run_id)}
                              className={`cursor-pointer border-b border-border/40 transition-colors hover:bg-accent/40 ${
                                selectedRun === r.run_id ? "bg-accent/40" : ""
                              }`}
                            >
                              <td className="relative px-5 py-2.5 font-mono text-xs font-medium text-foreground/80">
                                {selectedRun === r.run_id && (
                                  <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-full bg-brand/60" />
                                )}
                                <span className="inline-flex items-center gap-1.5">
                                  {r.run_id.length > 36 ? `${r.run_id.slice(0, 36)}…` : r.run_id}
                                  {annotated.has(r.run_id) && (
                                    <StickyNote
                                      className="h-3 w-3 text-amber-500"
                                      aria-label="Has annotation"
                                    />
                                  )}
                                </span>
                              </td>
                              <td className="px-5 py-2.5">
                                <StatusPill state={r.state} />
                              </td>
                              <td className="px-5 py-2.5 tabular-nums font-medium text-foreground/80">
                                {formatDuration(r.duration_seconds)}
                              </td>
                              <td className="px-5 py-2.5 font-medium text-muted-foreground">
                                {formatRelativeTime(r.start_date)}
                              </td>
                            </tr>
                          ))}
                          {pagedRuns.length === 0 && (
                            <tr>
                              <td colSpan={4}>
                                <EmptyState
                                  icon={Inbox}
                                  title="No runs in this range"
                                  hint="Try widening the time range or trigger a new run."
                                />
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                      {runs.length > PAGE_SIZE && (
                        <div className="flex items-center justify-between border-t border-border/60 px-5 py-2 text-xs text-muted-foreground">
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
                </motion.div>

                <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.1 }}>
                  <Card>
                    <CardHeader>
                      <CardTitle>Failure analysis</CardTitle>
                      <p className="text-xs font-medium text-muted-foreground">
                        {selectedRun ? "AI explains the selected run" : "Select a run to analyze"}
                      </p>
                    </CardHeader>
                    <CardContent className="space-y-5">
                      <AIPanel
                        mode="explain"
                        dagId={selected}
                        runId={selectedRun ?? undefined}
                        label="Analyze with AI"
                      />

                      {selectedRun && selected && (
                        <div className="border-t border-border pt-4">
                          <AnnotationPanel
                            key={`${selected}/${selectedRun}`}
                            dagId={selected}
                            runId={selectedRun}
                            onChange={onAnnotationChange(selectedRun)}
                          />
                        </div>
                      )}

                      {selectedRun && selected && (
                        <div className="border-t border-border pt-4">
                          <div className="mb-3">
                            <h4 className="text-sm font-medium">What changed?</h4>
                            <p className="text-xs font-medium text-muted-foreground">
                              Pick any baseline to compare task-by-task.
                            </p>
                          </div>
                          <DiffPanel dagId={selected} runId={selectedRun} />
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </motion.div>
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.2 }}>
                  <Card>
                    <CardHeader>
                      <CardTitle>Stakeholder summary</CardTitle>
                      <p className="text-xs font-medium text-muted-foreground">Plain-English status</p>
                    </CardHeader>
                    <CardContent>
                      <AIPanel mode="stakeholder" dagId={selected} label="Generate summary" />
                    </CardContent>
                  </Card>
                </motion.div>

                <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.25 }}>
                  <Card>
                    <CardHeader>
                      <CardTitle>Alerts</CardTitle>
                      <p className="text-xs font-medium text-muted-foreground">Failure notifications</p>
                    </CardHeader>
                    <CardContent>
                      <NotificationsPanel />
                    </CardContent>
                  </Card>
                </motion.div>
              </div>

              <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.28 }}>
                <Card>
                  <CardHeader>
                    <CardTitle>Alert config</CardTitle>
                    <p className="text-xs font-medium text-muted-foreground">
                      Mute, threshold, and quiet hours per DAG
                    </p>
                  </CardHeader>
                  <CardContent className="p-0">
                    <AlertConfigPanel />
                  </CardContent>
                </Card>
              </motion.div>

              <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.3 }}>
                <Card>
                  <CardHeader className="flex-row items-center justify-between">
                    <div>
                      <CardTitle>Tasks in selected run</CardTitle>
                      <p className="text-xs font-medium text-muted-foreground">
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
              </motion.div>
            </>
          )}
        </div>
        </>
        )}
      </main>
    </div>
  );
}
