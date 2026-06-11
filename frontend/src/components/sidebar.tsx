"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, BarChart3, FileText, LayoutDashboard, Search, Settings, Star, X } from "lucide-react";
import { getActiveEnv, type DAG } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { EnvSwitcher } from "@/components/env-switcher";

export type View = "dashboard" | "analytics" | "reports" | "settings";

type Props = {
  dags: DAG[];
  selected: string | null;
  onSelect: (dagId: string) => void;
  view: View;
  onChangeView: (view: View) => void;
  onEnvChange: (envName: string) => void;
};

const PINNED_STORAGE_PREFIX = "pipelinepulse:pinned-dags";
const LEGACY_PINNED_KEY = "pipelinepulse:pinned-dags"; // unscoped, for one-time migration

const NAV_ITEMS: Array<{ icon: typeof LayoutDashboard; label: string; view: View; enabled: boolean }> = [
  { icon: LayoutDashboard, label: "Dashboard", view: "dashboard", enabled: true },
  { icon: BarChart3, label: "Analytics", view: "analytics", enabled: true },
  { icon: FileText, label: "Reports", view: "reports", enabled: true },
  { icon: Settings, label: "Settings", view: "settings", enabled: true },
];

function pinnedKey(envName: string | null): string {
  return envName ? `${PINNED_STORAGE_PREFIX}:${envName}` : PINNED_STORAGE_PREFIX;
}

function readPinned(envName: string | null): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    let raw = window.localStorage.getItem(pinnedKey(envName));
    // One-time migration: if there's no per-env entry yet but a legacy unscoped key
    // exists, copy it into the env-scoped key (and leave the legacy key alone so other
    // envs don't lose it).
    if (!raw && envName) {
      raw = window.localStorage.getItem(LEGACY_PINNED_KEY);
      if (raw) window.localStorage.setItem(pinnedKey(envName), raw);
    }
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function writePinned(envName: string | null, pinned: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(pinnedKey(envName), JSON.stringify([...pinned]));
  } catch {
    // ignore quota / disabled-storage errors
  }
}

export function Sidebar({ dags, selected, onSelect, view, onChangeView, onEnvChange }: Props) {
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [activeEnv, setActiveEnv] = useState<string | null>(null);
  const filterRef = useRef<HTMLInputElement | null>(null);

  // Re-read pinned set whenever the active env changes. Switching env triggers
  // onEnvChange (which we wrap below) so the sidebar stays in sync without
  // duplicating env-state ownership.
  useEffect(() => {
    const env = getActiveEnv();
    setActiveEnv(env);
    setPinned(readPinned(env));
  }, []);

  const handleEnvChange = (envName: string) => {
    setActiveEnv(envName);
    setPinned(readPinned(envName));
    onEnvChange(envName);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inField =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (!inField && e.key === "/") {
        e.preventDefault();
        filterRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const togglePin = (dagId: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(dagId)) next.delete(dagId);
      else next.add(dagId);
      writePinned(activeEnv, next);
      return next;
    });
  };

  const q = filter.trim().toLowerCase();
  const matches = (d: DAG) => !q || d.dag_id.toLowerCase().includes(q);
  const pinnedDags = dags.filter((d) => pinned.has(d.dag_id) && matches(d));
  const unpinnedDags = dags.filter((d) => !pinned.has(d.dag_id) && matches(d));
  const totalAfterFilter = pinnedDags.length + unpinnedDags.length;

  const renderRow = (d: DAG, isPinned: boolean) => (
    <div
      key={d.dag_id}
      className={cn(
        "group relative flex items-center rounded-md transition-colors",
        selected === d.dag_id
          ? "bg-brand/10 text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {selected === d.dag_id && (
        <span className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full bg-brand" />
      )}
      <button
        onClick={() => onSelect(d.dag_id)}
        className={cn(
          "flex-1 truncate px-3 py-1.5 text-left font-mono text-xs",
          selected === d.dag_id ? "font-semibold" : "font-medium",
        )}
      >
        {d.dag_id}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          togglePin(d.dag_id);
        }}
        aria-label={isPinned ? `Unpin ${d.dag_id}` : `Pin ${d.dag_id}`}
        className={cn(
          "mr-1 rounded p-1 transition-opacity",
          isPinned
            ? "text-amber-500 opacity-100"
            : "opacity-0 hover:text-amber-500 group-hover:opacity-60",
        )}
      >
        <Star className={cn("h-3 w-3", isPinned && "fill-current")} />
      </button>
    </div>
  );

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="flex h-14 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-brand-foreground">
            <Activity className="h-4 w-4" />
          </span>
          <span className="text-sm font-bold tracking-tight">PipelinePulse</span>
        </div>
        <ThemeToggle />
      </div>

      <div className="border-b border-border px-3 py-2">
        <EnvSwitcher onChange={handleEnvChange} />
      </div>

      <nav className="flex flex-col gap-0.5 border-b border-border px-2 py-3">
        {NAV_ITEMS.map((item) => {
          const active = item.enabled && view === item.view;
          return (
            <button
              key={item.label}
              disabled={!item.enabled}
              onClick={() => item.enabled && onChangeView(item.view)}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-accent text-foreground font-semibold"
                  : item.enabled
                    ? "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    : "text-muted-foreground/50 cursor-not-allowed",
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
              {!item.enabled && (
                <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-muted-foreground/60">
                  soon
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="border-b border-border px-3 py-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/70" />
          <input
            ref={filterRef}
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setFilter("");
                e.currentTarget.blur();
              }
            }}
            placeholder="Filter DAGs"
            aria-label="Filter DAGs"
            className="h-7 w-full rounded-md border border-border bg-background pl-7 pr-7 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {filter ? (
            <button
              onClick={() => setFilter("")}
              aria-label="Clear filter"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          ) : (
            <kbd className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded border border-border bg-muted px-1 font-mono text-[9px] font-semibold text-muted-foreground">
              /
            </kbd>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 py-3">
        {totalAfterFilter === 0 ? (
          <div className="px-3 py-6 text-center text-[11px] font-medium text-muted-foreground">
            {q ? `No DAGs match "${filter}"` : "No DAGs yet"}
          </div>
        ) : (
          <>
            {pinnedDags.length > 0 && (
              <>
                <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  Pinned
                </div>
                <div className="flex flex-col gap-0.5">
                  {pinnedDags.map((d) => renderRow(d, true))}
                </div>
                {unpinnedDags.length > 0 && <div className="my-3 border-t border-border" />}
              </>
            )}

            {unpinnedDags.length > 0 && (
              <>
                <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  {pinnedDags.length > 0 ? "All DAGs" : "DAGs"}
                  {q && (
                    <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/70">
                      · {totalAfterFilter} match{totalAfterFilter === 1 ? "" : "es"}
                    </span>
                  )}
                </div>
                <div className="flex flex-col gap-0.5">
                  {unpinnedDags.map((d) => renderRow(d, false))}
                </div>
              </>
            )}
          </>
        )}
      </div>

      <div className="border-t border-border p-3 text-[11px] font-medium text-muted-foreground">
        Auto-syncs from Airflow every 2 min
      </div>
    </aside>
  );
}
