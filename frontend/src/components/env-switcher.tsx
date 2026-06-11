"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, Server } from "lucide-react";
import { api, getActiveEnv, setActiveEnv, type EnvironmentInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  onChange: (envName: string) => void;
};

export function EnvSwitcher({ onChange }: Props) {
  const [envs, setEnvs] = useState<EnvironmentInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string | null>(getActiveEnv());
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const reload = async () => {
    try {
      const items = await api.listEnvironments();
      setEnvs(items);
      // If no active env is set yet, pick the default. Persist it so subsequent
      // requests carry an explicit env (avoids ambiguity when more envs are added).
      if (!active && items.length > 0) {
        const def = items.find((e) => e.is_default) ?? items[0];
        setActiveEnv(def.name);
        setActive(def.name);
        onChange(def.name);
      } else if (active && !items.some((e) => e.name === active)) {
        // Active env was deleted — fall back to default
        const def = items.find((e) => e.is_default) ?? items[0];
        if (def) {
          setActiveEnv(def.name);
          setActive(def.name);
          onChange(def.name);
        }
      }
    } catch {
      setEnvs([]);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const select = (name: string) => {
    setActiveEnv(name);
    setActive(name);
    setOpen(false);
    onChange(name);
  };

  if (envs.length === 0) {
    return null;
  }

  // Single env — render as a non-interactive label so the user knows what they're seeing.
  if (envs.length === 1) {
    return (
      <div className="flex items-center gap-1.5 rounded-md border border-border bg-background/40 px-2 py-1 text-[11px] font-mono text-muted-foreground">
        <Server className="h-3 w-3" />
        {envs[0].name}
      </div>
    );
  }

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1.5 rounded-md border border-border bg-background/60 px-2 py-1 text-[11px] font-mono font-semibold transition-colors",
          "hover:bg-accent",
        )}
        aria-label="Switch environment"
      >
        <Server className="h-3 w-3 text-muted-foreground" />
        <span className="max-w-[120px] truncate">{active ?? "—"}</span>
        <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-56 rounded-md border border-border bg-card p-1 shadow-lg">
          <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
            Environments
          </div>
          {envs.map((e) => {
            const isActive = e.name === active;
            return (
              <button
                key={e.id}
                onClick={() => select(e.name)}
                disabled={!e.enabled}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors",
                  isActive
                    ? "bg-accent text-foreground"
                    : "hover:bg-accent/50 text-muted-foreground hover:text-foreground",
                  !e.enabled && "opacity-50 cursor-not-allowed",
                )}
              >
                <div className="flex min-w-0 flex-col">
                  <span className="truncate font-mono font-semibold">{e.name}</span>
                  <span className="truncate text-[10px] text-muted-foreground/80">
                    {e.airflow_base_url}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {e.is_default && (
                    <span className="rounded-full bg-brand/10 px-1.5 py-0.5 text-[9px] font-bold text-brand">
                      DEFAULT
                    </span>
                  )}
                  {isActive && <Check className="h-3 w-3 text-success" />}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
