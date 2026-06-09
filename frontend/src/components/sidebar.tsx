"use client";

import { useEffect, useState } from "react";
import { Activity, BarChart3, FileText, LayoutDashboard, Settings, Star } from "lucide-react";
import type { DAG } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";

export type View = "dashboard" | "analytics" | "reports" | "settings";

type Props = {
  dags: DAG[];
  selected: string | null;
  onSelect: (dagId: string) => void;
  view: View;
  onChangeView: (view: View) => void;
};

const STORAGE_KEY = "pipelinepulse:pinned-dags";

const NAV_ITEMS: Array<{ icon: typeof LayoutDashboard; label: string; view: View; enabled: boolean }> = [
  { icon: LayoutDashboard, label: "Dashboard", view: "dashboard", enabled: true },
  { icon: BarChart3, label: "Analytics", view: "analytics", enabled: true },
  { icon: FileText, label: "Reports", view: "reports", enabled: false },
  { icon: Settings, label: "Settings", view: "settings", enabled: false },
];

function readPinned(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function writePinned(pinned: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...pinned]));
  } catch {
    // ignore quota / disabled-storage errors
  }
}

export function Sidebar({ dags, selected, onSelect, view, onChangeView }: Props) {
  const [pinned, setPinned] = useState<Set<string>>(new Set());

  useEffect(() => {
    setPinned(readPinned());
  }, []);

  const togglePin = (dagId: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(dagId)) next.delete(dagId);
      else next.add(dagId);
      writePinned(next);
      return next;
    });
  };

  const pinnedDags = dags.filter((d) => pinned.has(d.dag_id));
  const unpinnedDags = dags.filter((d) => !pinned.has(d.dag_id));

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

      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 py-3">
        {pinnedDags.length > 0 && (
          <>
            <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Pinned
            </div>
            <div className="flex flex-col gap-0.5">
              {pinnedDags.map((d) => renderRow(d, true))}
            </div>
            <div className="my-3 border-t border-border" />
          </>
        )}

        <div className="px-3 pb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
          {pinnedDags.length > 0 ? "All DAGs" : "DAGs"}
        </div>
        <div className="flex flex-col gap-0.5">
          {unpinnedDags.map((d) => renderRow(d, false))}
        </div>
      </div>

      <div className="border-t border-border p-3 text-[11px] font-medium text-muted-foreground">
        Auto-syncs from Airflow every 2 min
      </div>
    </aside>
  );
}
