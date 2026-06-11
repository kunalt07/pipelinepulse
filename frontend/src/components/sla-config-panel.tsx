"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Clock, Loader2 } from "lucide-react";
import { api, type SlaConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

type SaveState = "idle" | "saving" | "saved" | "error";

type RowProps = {
  config: SlaConfig;
  onChange: (next: SlaConfig) => void;
};

function ConfigRow({ config, onChange }: RowProps) {
  const [local, setLocal] = useState<SlaConfig>(config);
  const [save, setSave] = useState<SaveState>("idle");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocal(config);
  }, [config]);

  const persist = (next: SlaConfig) => {
    setLocal(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setSave("saving");
      try {
        const saved = await api.updateSlaConfig(next.dag_id, {
          enabled: next.enabled,
          deadline_time: next.deadline_time,
          deadline_timezone: next.deadline_timezone,
          max_runtime_minutes: next.max_runtime_minutes,
        });
        setSave("saved");
        onChange(saved);
        setTimeout(() => setSave("idle"), 1500);
      } catch {
        setSave("error");
        setTimeout(() => setSave("idle"), 3000);
      }
    }, 400);
  };

  const hasDeadline = !!local.deadline_time;

  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-3 border-b border-border/50 px-4 py-3 text-xs",
        !local.enabled && "opacity-50",
      )}
    >
      <div className="min-w-0 truncate font-mono text-[12px] font-semibold">{local.dag_id}</div>

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        <input
          type="checkbox"
          checked={local.enabled}
          onChange={(e) => persist({ ...local, enabled: e.target.checked })}
          className="h-3.5 w-3.5 cursor-pointer"
        />
        Enabled
      </label>

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        Deadline
        <input
          type="time"
          value={local.deadline_time ?? ""}
          onChange={(e) => persist({ ...local, deadline_time: e.target.value || null })}
          className="h-7 rounded border border-border bg-background px-1.5 font-mono"
        />
      </label>

      <input
        type="text"
        placeholder="UTC"
        value={local.deadline_timezone ?? ""}
        onChange={(e) =>
          persist({ ...local, deadline_timezone: e.target.value.trim() || null })
        }
        disabled={!hasDeadline}
        className="h-7 w-32 rounded border border-border bg-background px-2 font-mono text-[11px] disabled:opacity-50"
        title="IANA timezone, e.g. America/Los_Angeles"
      />

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        Max
        <input
          type="number"
          min={1}
          max={1440}
          value={local.max_runtime_minutes ?? ""}
          placeholder="—"
          onChange={(e) => {
            const v = e.target.value === "" ? null : Math.max(1, Math.min(1440, Number(e.target.value)));
            persist({ ...local, max_runtime_minutes: v });
          }}
          className="h-7 w-16 rounded border border-border bg-background px-2 text-center font-mono"
        />
        min
      </label>

      <div className="flex w-5 items-center justify-center">
        {save === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {save === "saved" && <Check className="h-3.5 w-3.5 text-success" />}
        {save === "error" && <span className="text-[10px] text-danger">err</span>}
      </div>
    </div>
  );
}

export function SlaConfigPanel() {
  const [configs, setConfigs] = useState<SlaConfig[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const c = await api.slaConfigs();
      setConfigs(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load SLA configs");
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (error) return <p className="px-4 py-3 text-xs text-danger">{error}</p>;
  if (configs === null) {
    return (
      <div className="space-y-2 px-4 py-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 rounded shimmer" />
        ))}
      </div>
    );
  }

  if (configs.length === 0) {
    return <p className="px-4 py-3 text-xs text-muted-foreground">No DAGs to configure.</p>;
  }

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-3 border-b border-border bg-muted/30 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
        <div>DAG</div>
        <div>On</div>
        <div className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          Deadline
        </div>
        <div>Timezone</div>
        <div>Max runtime</div>
        <div className="w-5" />
      </div>
      {configs.map((c) => (
        <ConfigRow
          key={c.dag_id}
          config={c}
          onChange={(next) => {
            setConfigs((prev) =>
              prev ? prev.map((p) => (p.dag_id === next.dag_id ? next : p)) : prev,
            );
          }}
        />
      ))}
    </div>
  );
}
