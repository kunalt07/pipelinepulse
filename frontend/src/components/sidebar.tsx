"use client";

import { useEffect, useState } from "react";
import { Activity, Star } from "lucide-react";
import type { DAG } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";

type Props = {
  dags: DAG[];
  selected: string | null;
  onSelect: (dagId: string) => void;
};

const STORAGE_KEY = "pipelinepulse:pinned-dags";

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

export function Sidebar({ dags, selected, onSelect }: Props) {
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
        "group flex items-center rounded-md transition-colors",
        selected === d.dag_id
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
      )}
    >
      <button
        onClick={() => onSelect(d.dag_id)}
        className="flex-1 truncate px-2 py-1.5 text-left font-mono text-xs"
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
    <aside className="flex h-screen w-64 shrink-0 flex-col border-r bg-card">
      <div className="flex h-14 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4" />
          <span className="text-sm font-semibold tracking-tight">PipelinePulse</span>
        </div>
        <ThemeToggle />
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 py-3">
        {pinnedDags.length > 0 && (
          <>
            <div className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Pinned
            </div>
            <nav className="flex flex-col gap-0.5">
              {pinnedDags.map((d) => renderRow(d, true))}
            </nav>
            <div className="my-3 border-t" />
          </>
        )}

        <div className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {pinnedDags.length > 0 ? "All DAGs" : "DAGs"}
        </div>
        <nav className="flex flex-col gap-0.5">
          {unpinnedDags.map((d) => renderRow(d, false))}
        </nav>
      </div>

      <div className="border-t p-3 text-[11px] text-muted-foreground">
        Auto-syncs from Airflow every 2 min
      </div>
    </aside>
  );
}
