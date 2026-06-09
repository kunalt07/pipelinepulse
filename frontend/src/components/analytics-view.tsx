"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, BarChart3 } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type AnalyticsResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDuration } from "@/lib/utils";
import { EmptyState } from "@/components/empty-state";

const cardEntry = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const },
};

type Range = "7d" | "30d";

function Trend({ value, invert = false }: { value: number | null; invert?: boolean }) {
  if (value === null || value === 0) {
    return <span className="text-[11px] font-medium text-muted-foreground">—</span>;
  }
  const positive = invert ? value < 0 : value > 0;
  const Icon = value > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${
        positive ? "text-success" : "text-danger"
      }`}
    >
      <Icon className="h-3 w-3" />
      {value > 0 ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

function StatTile({
  label,
  value,
  trend,
  invertTrend = false,
  hint,
}: {
  label: string;
  value: string;
  trend: number | null;
  invertTrend?: boolean;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
      <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <div className="text-[2rem] font-bold leading-none tracking-tight tabular-nums">
          {value}
        </div>
        <Trend value={trend} invert={invertTrend} />
      </div>
      {hint && <div className="mt-2 text-[11px] font-medium text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function AnalyticsView() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [range, setRange] = useState<Range>("7d");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setData(null);
    api
      .analytics(range)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  if (error) {
    return (
      <div className="p-6">
        <p className="text-sm text-danger">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight">Analytics</h2>
          <p className="text-xs font-medium text-muted-foreground">
            Cross-DAG aggregates · current vs prior {range === "7d" ? "week" : "30 days"}
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-border bg-background/50 p-0.5">
          {(["7d", "30d"] as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`rounded px-3 py-1 text-xs font-semibold transition-colors ${
                range === r
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r === "7d" ? "Last 7 days" : "Last 30 days"}
            </button>
          ))}
        </div>
      </div>

      {!data ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-28 rounded-lg shimmer" />
          ))}
        </div>
      ) : (
        <>
          <motion.section
            {...cardEntry}
            className="grid grid-cols-2 gap-3 lg:grid-cols-5"
          >
            <StatTile
              label="Total runs"
              value={data.totals.current.total.toLocaleString()}
              trend={data.totals.deltas.total}
              hint="Across all DAGs"
            />
            <StatTile
              label="Failures"
              value={data.totals.current.failed.toLocaleString()}
              trend={data.totals.deltas.failed}
              invertTrend
              hint="Lower is better"
            />
            <StatTile
              label="Success rate"
              value={`${data.totals.current.success_rate}%`}
              trend={data.totals.deltas.success_rate}
              hint="Across all DAGs"
            />
            <StatTile
              label="Avg duration"
              value={formatDuration(data.totals.current.avg_duration_seconds)}
              trend={data.totals.deltas.avg_duration_seconds}
              invertTrend
              hint="Per run"
            />
            <StatTile
              label="Total runtime"
              value={formatDuration(data.totals.current.total_runtime_seconds)}
              trend={data.totals.deltas.total_runtime_seconds}
              hint="Cumulative compute"
            />
          </motion.section>

          <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.05 }}>
            <Card>
              <CardHeader>
                <CardTitle>Failure rate trend</CardTitle>
                <p className="text-xs font-medium text-muted-foreground">
                  Daily failure percentage across all DAGs
                </p>
              </CardHeader>
              <CardContent>
                {data.daily.length === 0 ? (
                  <EmptyState
                    icon={BarChart3}
                    title="No runs in this range"
                    className="h-56"
                  />
                ) : (
                  <div className="h-64 w-full">
                    <ResponsiveContainer>
                      <LineChart data={data.daily} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
                        <XAxis
                          dataKey="date"
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          tickFormatter={(v: number) => `${v}%`}
                          width={40}
                        />
                        <Tooltip
                          contentStyle={{
                            background: "hsl(var(--card))",
                            border: "1px solid hsl(var(--border))",
                            borderRadius: 6,
                            fontSize: 12,
                          }}
                          labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 600 }}
                          formatter={(v: number, name: string) => {
                            if (name === "failure_rate") return [`${v}%`, "Failure rate"];
                            return [v, name];
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="failure_rate"
                          stroke="hsl(var(--danger))"
                          strokeWidth={2}
                          dot={{ r: 3, fill: "hsl(var(--danger))" }}
                          activeDot={{ r: 5 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>

          <div className="grid gap-6 lg:grid-cols-2">
            <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.1 }}>
              <Card>
                <CardHeader>
                  <CardTitle>Slowest DAGs</CardTitle>
                  <p className="text-xs font-medium text-muted-foreground">
                    Top 5 by average run duration
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  {data.slowest_dags.length === 0 ? (
                    <p className="px-5 py-6 text-xs text-muted-foreground">No data yet.</p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {data.slowest_dags.map((d) => (
                        <li key={d.dag_id} className="flex items-center justify-between px-5 py-3 text-sm">
                          <div className="min-w-0">
                            <div className="truncate font-mono text-xs font-semibold">{d.dag_id}</div>
                            <div className="text-[11px] font-medium text-muted-foreground">
                              {d.total_runs} runs · {d.failure_rate}% fail
                            </div>
                          </div>
                          <div className="font-semibold tabular-nums">
                            {formatDuration(d.avg_duration_seconds)}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </motion.div>

            <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.15 }}>
              <Card>
                <CardHeader>
                  <CardTitle>Most failure-prone</CardTitle>
                  <p className="text-xs font-medium text-muted-foreground">
                    Top 5 by failure rate
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  {data.most_failures.length === 0 ? (
                    <p className="px-5 py-6 text-xs text-muted-foreground">No data yet.</p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {data.most_failures.map((d) => (
                        <li key={d.dag_id} className="flex items-center justify-between px-5 py-3 text-sm">
                          <div className="min-w-0">
                            <div className="truncate font-mono text-xs font-semibold">{d.dag_id}</div>
                            <div className="text-[11px] font-medium text-muted-foreground">
                              {d.failures} fails / {d.total_runs} runs
                            </div>
                          </div>
                          <div
                            className={`font-semibold tabular-nums ${
                              d.failure_rate > 0 ? "text-danger" : "text-muted-foreground"
                            }`}
                          >
                            {d.failure_rate}%
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          </div>

          <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.2 }}>
            <Card>
              <CardHeader>
                <CardTitle>Busiest hours</CardTitle>
                <p className="text-xs font-medium text-muted-foreground">
                  Run distribution by hour of day (UTC)
                </p>
              </CardHeader>
              <CardContent>
                <div className="h-56 w-full">
                  <ResponsiveContainer>
                    <BarChart data={data.busy_hours} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
                      <XAxis
                        dataKey="hour"
                        tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(h: number) => `${h}h`}
                        interval={1}
                      />
                      <YAxis
                        tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        width={32}
                        allowDecimals={false}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "hsl(var(--card))",
                          border: "1px solid hsl(var(--border))",
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                        labelFormatter={(h: number) => `${h.toString().padStart(2, "0")}:00 UTC`}
                      />
                      <Bar dataKey="total" radius={[2, 2, 0, 0]} maxBarSize={28}>
                        {data.busy_hours.map((h) => (
                          <Cell
                            key={h.hour}
                            fill={
                              h.failed > 0 && h.total > 0 && h.failed / h.total >= 0.2
                                ? "hsl(var(--danger))"
                                : "hsl(var(--success))"
                            }
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        </>
      )}
    </div>
  );
}
