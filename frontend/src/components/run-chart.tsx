"use client";

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DAGRun } from "@/lib/api";
import { formatDuration } from "@/lib/utils";

type Datum = {
  index: number;
  time: string;
  fullTime: string;
  minutes: number;
  seconds: number;
  state: string;
  runId: string;
};

const COLORS: Record<string, string> = {
  success: "hsl(142 71% 45%)",
  failed: "hsl(0 72% 60%)",
  running: "hsl(217 91% 60%)",
  queued: "hsl(240 5% 50%)",
};

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, Math.min(idx, sorted.length - 1))];
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Datum }> }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 flex items-center gap-2">
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: COLORS[d.state] ?? COLORS.queued }}
        />
        <span className="font-medium capitalize">{d.state}</span>
      </div>
      <div className="font-mono text-muted-foreground">{d.fullTime}</div>
      <div className="mt-1 tabular-nums">
        Duration: <span className="font-medium text-foreground">{formatDuration(d.seconds)}</span>
      </div>
    </div>
  );
}

export function RunChart({ runs }: { runs: DAGRun[] }) {
  const data: Datum[] = [...runs]
    .reverse()
    .filter((r) => r.start_date)
    .map((r, i) => {
      const dt = new Date(r.start_date!);
      return {
        index: i,
        time: dt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }),
        fullTime: dt.toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
        minutes: (r.duration_seconds ?? 0) / 60,
        seconds: r.duration_seconds ?? 0,
        state: r.state,
        runId: r.run_id,
      };
    });

  if (data.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
        No runs yet
      </div>
    );
  }

  const successDurations = data.filter((d) => d.state === "success").map((d) => d.minutes);
  const p95 = percentile(successDurations, 95);

  const tickInterval = Math.max(0, Math.floor(data.length / 6) - 1);

  return (
    <div className="space-y-3">
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.4} vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              interval={tickInterval}
              minTickGap={20}
            />
            <YAxis
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `${v}m`}
              width={44}
            />
            {p95 > 0 && (
              <ReferenceLine
                y={p95}
                stroke="hsl(var(--muted-foreground))"
                strokeDasharray="2 4"
                strokeOpacity={0.5}
                label={{
                  value: `p95 ${p95.toFixed(1)}m`,
                  position: "right",
                  fill: "hsl(var(--muted-foreground))",
                  fontSize: 10,
                }}
              />
            )}
            <Tooltip
              cursor={{ fill: "hsl(var(--accent))", opacity: 0.4 }}
              content={<CustomTooltip />}
            />
            <Bar dataKey="minutes" radius={[2, 2, 0, 0]} maxBarSize={32}>
              {data.map((d) => (
                <Cell key={d.runId} fill={COLORS[d.state] ?? COLORS.queued} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Legend />
    </div>
  );
}

function Legend() {
  const items: Array<[string, string]> = [
    ["success", "Success"],
    ["failed", "Failed"],
    ["running", "Running"],
  ];
  return (
    <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
      {items.map(([key, label]) => (
        <div key={key} className="flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-sm"
            style={{ backgroundColor: COLORS[key] }}
          />
          {label}
        </div>
      ))}
    </div>
  );
}
