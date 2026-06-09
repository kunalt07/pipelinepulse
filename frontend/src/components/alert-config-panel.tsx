"use client";

import { useEffect, useRef, useState } from "react";
import { BellOff, Check, Loader2 } from "lucide-react";
import { api, type AlertConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

type SaveState = "idle" | "saving" | "saved" | "error";

type RowProps = {
  config: AlertConfig;
  onChange: (next: AlertConfig) => void;
};

function ConfigRow({ config, onChange }: RowProps) {
  const [local, setLocal] = useState<AlertConfig>(config);
  const [save, setSave] = useState<SaveState>("idle");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocal(config);
  }, [config]);

  const persist = (next: AlertConfig) => {
    setLocal(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setSave("saving");
      try {
        const saved = await api.updateAlertConfig(next.dag_id, {
          muted: next.muted,
          min_consecutive_failures: next.min_consecutive_failures,
          quiet_hours_start: next.quiet_hours_start,
          quiet_hours_end: next.quiet_hours_end,
          quiet_timezone: next.quiet_timezone,
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

  const hasQuiet = !!(local.quiet_hours_start && local.quiet_hours_end);

  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-3 border-b border-border/50 px-4 py-3 text-xs",
        local.muted && "opacity-60",
      )}
    >
      <div className="min-w-0">
        <div className="truncate font-mono text-[12px] font-semibold">{local.dag_id}</div>
        {local.muted && (
          <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
            <BellOff className="h-3 w-3" />
            Muted
          </div>
        )}
      </div>

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        <input
          type="checkbox"
          checked={local.muted}
          onChange={(e) => persist({ ...local, muted: e.target.checked })}
          className="h-3.5 w-3.5 cursor-pointer"
        />
        Mute
      </label>

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        After
        <input
          type="number"
          min={1}
          max={20}
          value={local.min_consecutive_failures}
          onChange={(e) =>
            persist({
              ...local,
              min_consecutive_failures: Math.max(1, Math.min(20, Number(e.target.value) || 1)),
            })
          }
          className="h-7 w-14 rounded border border-border bg-background px-2 text-center font-mono"
        />
        fails
      </label>

      <label className="flex items-center gap-1.5 font-medium text-muted-foreground">
        Quiet
        <input
          type="time"
          value={local.quiet_hours_start ?? ""}
          onChange={(e) =>
            persist({ ...local, quiet_hours_start: e.target.value || null })
          }
          className="h-7 rounded border border-border bg-background px-1.5 font-mono"
        />
        →
        <input
          type="time"
          value={local.quiet_hours_end ?? ""}
          onChange={(e) =>
            persist({ ...local, quiet_hours_end: e.target.value || null })
          }
          className="h-7 rounded border border-border bg-background px-1.5 font-mono"
        />
      </label>

      <input
        type="text"
        placeholder="UTC"
        value={local.quiet_timezone ?? ""}
        onChange={(e) =>
          persist({ ...local, quiet_timezone: e.target.value.trim() || null })
        }
        disabled={!hasQuiet}
        className="h-7 w-36 rounded border border-border bg-background px-2 font-mono text-[11px] disabled:opacity-50"
        title="IANA timezone, e.g. America/Los_Angeles"
      />

      <div className="flex w-5 items-center justify-center">
        {save === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {save === "saved" && <Check className="h-3.5 w-3.5 text-success" />}
        {save === "error" && <span className="text-[10px] text-danger">err</span>}
      </div>
    </div>
  );
}

export function AlertConfigPanel() {
  const [configs, setConfigs] = useState<AlertConfig[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const c = await api.alertConfigs();
      setConfigs(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load configs");
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (error) return <p className="text-xs text-danger">{error}</p>;
  if (configs === null) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 rounded shimmer" />
        ))}
      </div>
    );
  }

  if (configs.length === 0) {
    return <p className="text-xs text-muted-foreground">No DAGs to configure.</p>;
  }

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-3 border-b border-border bg-muted/30 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
        <div>DAG</div>
        <div>Mute</div>
        <div>Threshold</div>
        <div>Quiet hours</div>
        <div>Timezone</div>
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
