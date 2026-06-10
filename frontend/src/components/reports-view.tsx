"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Calendar,
  Check,
  Download,
  FileCode2,
  FileText,
  Loader2,
  Sparkles,
} from "lucide-react";
import {
  api,
  downloadBlob,
  type ReportFormat,
  type ReportHistoryItem,
  type ReportRange,
  type ReportSchedule,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { cn } from "@/lib/utils";

const cardEntry = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const },
};

type SaveState = "idle" | "saving" | "saved" | "error";

const FORMAT_OPTIONS: { value: ReportFormat; label: string; icon: typeof FileText }[] = [
  { value: "md", label: "Markdown", icon: FileCode2 },
  { value: "html", label: "HTML", icon: FileText },
  { value: "pdf", label: "PDF", icon: FileText },
];

const RANGE_OPTIONS: { value: ReportRange; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

const DAY_OF_WEEK_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function PillGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-md border border-border bg-background/50 p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded px-3 py-1 text-xs font-semibold transition-colors",
            value === opt.value
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function GenerateCard({
  onGenerated,
}: {
  onGenerated: (item: { id: number; format: ReportFormat; previewBlob: Blob }) => void;
}) {
  const [range, setRange] = useState<ReportRange>("7d");
  const [format, setFormat] = useState<ReportFormat>("html");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSummary, setLastSummary] = useState<string | null>(null);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const { blob, filename, reportId, summary } = await api.generateReport(range, format);
      downloadBlob(blob, filename ?? `pipelinepulse-${range}.${format}`);
      if (reportId) onGenerated({ id: reportId, format, previewBlob: blob });
      if (summary) setLastSummary(summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Generate report</CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          Cross-DAG snapshot. Downloads immediately and lands in history below.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <PillGroup options={RANGE_OPTIONS} value={range} onChange={setRange} />
          <PillGroup
            options={FORMAT_OPTIONS.map((f) => ({ value: f.value, label: f.label }))}
            value={format}
            onChange={setFormat}
          />
          <Button onClick={generate} disabled={generating} size="sm">
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Generate
          </Button>
        </div>
        {lastSummary && !generating && (
          <div className="rounded-md border border-success/30 bg-success/5 px-3 py-2 text-xs font-medium text-foreground">
            <span className="font-semibold text-success">Generated:</span> {lastSummary}
          </div>
        )}
        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
            {error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ScheduleCard() {
  const [schedule, setSchedule] = useState<ReportSchedule | null>(null);
  const [save, setSave] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api
      .getReportSchedule()
      .then(setSchedule)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  const persist = (next: ReportSchedule) => {
    setSchedule(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setSave("saving");
      try {
        const saved = await api.updateReportSchedule({
          enabled: next.enabled,
          frequency: next.frequency,
          day_of_week: next.day_of_week,
          day_of_month: next.day_of_month,
          hour: next.hour,
          range: next.range,
          format: next.format,
          webhook_url: next.webhook_url,
        });
        setSchedule(saved);
        setSave("saved");
        setTimeout(() => setSave("idle"), 1500);
      } catch {
        setSave("error");
        setTimeout(() => setSave("idle"), 3000);
      }
    }, 500);
  };

  if (error) {
    return (
      <Card>
        <CardContent className="p-4 text-xs text-danger">{error}</CardContent>
      </Card>
    );
  }
  if (!schedule) {
    return (
      <Card>
        <CardContent className="space-y-2 p-4">
          <div className="h-4 w-1/3 rounded shimmer" />
          <div className="h-8 rounded shimmer" />
          <div className="h-8 rounded shimmer" />
        </CardContent>
      </Card>
    );
  }

  const webhookConfigured =
    !!(schedule.webhook_url && schedule.webhook_url.trim()) || schedule.global_webhook_configured;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>Schedule</CardTitle>
          <p className="text-xs font-medium text-muted-foreground">
            Auto-generate and ping a webhook when ready. Slack/Discord get a link, not the file.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {save === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          {save === "saved" && <Check className="h-3.5 w-3.5 text-success" />}
          {save === "error" && <span className="text-[10px] font-semibold text-danger">save failed</span>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={schedule.enabled}
            onChange={(e) => persist({ ...schedule, enabled: e.target.checked })}
            className="h-4 w-4 cursor-pointer"
          />
          Enable scheduled reports
        </label>

        <div className={cn("space-y-3", !schedule.enabled && "pointer-events-none opacity-50")}>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="font-semibold text-muted-foreground">Frequency</span>
            <PillGroup
              options={[
                { value: "weekly", label: "Weekly" },
                { value: "monthly", label: "Monthly" },
              ]}
              value={schedule.frequency}
              onChange={(v) => persist({ ...schedule, frequency: v })}
            />

            {schedule.frequency === "weekly" ? (
              <label className="flex items-center gap-2 font-medium text-muted-foreground">
                Day
                <select
                  value={schedule.day_of_week}
                  onChange={(e) =>
                    persist({ ...schedule, day_of_week: Number(e.target.value) })
                  }
                  className="h-7 rounded border border-border bg-background px-2 font-mono text-[11px]"
                >
                  {DAY_OF_WEEK_LABELS.map((label, i) => (
                    <option key={label} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="flex items-center gap-2 font-medium text-muted-foreground">
                Day of month
                <input
                  type="number"
                  min={1}
                  max={28}
                  value={schedule.day_of_month}
                  onChange={(e) =>
                    persist({
                      ...schedule,
                      day_of_month: Math.max(1, Math.min(28, Number(e.target.value) || 1)),
                    })
                  }
                  className="h-7 w-14 rounded border border-border bg-background px-2 text-center font-mono"
                />
              </label>
            )}

            <label className="flex items-center gap-2 font-medium text-muted-foreground">
              Hour (UTC)
              <input
                type="number"
                min={0}
                max={23}
                value={schedule.hour}
                onChange={(e) =>
                  persist({
                    ...schedule,
                    hour: Math.max(0, Math.min(23, Number(e.target.value) || 0)),
                  })
                }
                className="h-7 w-14 rounded border border-border bg-background px-2 text-center font-mono"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="font-semibold text-muted-foreground">Report</span>
            <PillGroup
              options={RANGE_OPTIONS}
              value={schedule.range}
              onChange={(v) => persist({ ...schedule, range: v })}
            />
            <PillGroup
              options={FORMAT_OPTIONS.map((f) => ({ value: f.value, label: f.label }))}
              value={schedule.format}
              onChange={(v) => persist({ ...schedule, format: v })}
            />
          </div>

          <label className="flex flex-col gap-1 text-xs">
            <span className="font-semibold text-muted-foreground">Webhook URL (optional override)</span>
            <input
              type="text"
              placeholder={
                schedule.global_webhook_configured
                  ? "Leave blank to use the global WEBHOOK_URL"
                  : "https://hooks.slack.com/..."
              }
              value={schedule.webhook_url ?? ""}
              onChange={(e) => persist({ ...schedule, webhook_url: e.target.value || null })}
              className="h-8 rounded border border-border bg-background px-2 font-mono text-[11px]"
            />
            {!webhookConfigured && (
              <span className="text-[10px] text-warning">
                No webhook configured — schedule will run but won&apos;t notify anyone. Set
                WEBHOOK_URL in env or fill this field.
              </span>
            )}
          </label>

          {schedule.last_sent_at && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Calendar className="h-3 w-3" />
              Last sent {schedule.last_sent_at}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function HistoryCard({
  history,
  reload,
}: {
  history: ReportHistoryItem[] | null;
  reload: () => void;
}) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const onDownload = async (id: number, fmt: ReportFormat) => {
    const key = `${id}:${fmt}`;
    setDownloading(key);
    try {
      const { blob, filename } = await api.downloadStoredReport(id, fmt);
      downloadBlob(blob, filename ?? `pipelinepulse-${id}.${fmt}`);
    } catch (e) {
      console.error(e);
    } finally {
      setDownloading(null);
    }
  };

  if (history === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-12 rounded shimmer" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>History</CardTitle>
          <p className="text-xs font-medium text-muted-foreground">
            Re-render any past report in any format. Stats reflect current DB state.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={reload}>
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {history.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No reports yet"
            hint="Generate one above, or enable scheduled delivery."
            className="py-10"
          />
        ) : (
          <ul className="divide-y divide-border">
            {history.map((h) => (
              <li
                key={h.id}
                className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] font-semibold">
                      {h.range === "7d" ? "Last 7 days" : "Last 30 days"}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize",
                        h.source === "scheduled"
                          ? "border-brand/30 bg-brand/10 text-brand"
                          : "border-border bg-muted text-muted-foreground",
                      )}
                    >
                      {h.source === "scheduled" && <Sparkles className="h-2.5 w-2.5" />}
                      {h.source}
                    </span>
                    {h.delivered && (
                      <span
                        className={cn(
                          "text-[10px] font-medium",
                          h.delivered === "ok"
                            ? "text-success"
                            : h.delivered === "skipped"
                              ? "text-muted-foreground"
                              : "text-danger",
                        )}
                      >
                        delivery: {h.delivered}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] font-medium text-muted-foreground">
                    {h.summary_line ?? "—"} · {h.generated_at}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {(["md", "html", "pdf"] as ReportFormat[]).map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => onDownload(h.id, fmt)}
                      disabled={downloading === `${h.id}:${fmt}`}
                      className={cn(
                        "rounded border border-border px-2 py-1 font-mono text-[10px] font-semibold uppercase transition-colors",
                        "hover:bg-accent hover:text-accent-foreground disabled:opacity-50",
                      )}
                      title={`Download as ${fmt.toUpperCase()}`}
                    >
                      {downloading === `${h.id}:${fmt}` ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        fmt
                      )}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function ReportsView() {
  const [history, setHistory] = useState<ReportHistoryItem[] | null>(null);

  const load = async () => {
    try {
      const items = await api.reportHistory();
      setHistory(items);
    } catch {
      setHistory([]);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Reports</h2>
        <p className="text-xs font-medium text-muted-foreground">
          Shareable run-history snapshots — for stakeholders or your own bookkeeping.
        </p>
      </div>

      <motion.div {...cardEntry}>
        <GenerateCard onGenerated={() => void load()} />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.05 }}>
        <ScheduleCard />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.1 }}>
        <HistoryCard history={history} reload={load} />
      </motion.div>
    </div>
  );
}
