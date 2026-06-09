"use client";

import { Activity } from "lucide-react";
import type { DAG } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";

type Props = {
  dags: DAG[];
  selected: string | null;
  onSelect: (dagId: string) => void;
};

export function Sidebar({ dags, selected, onSelect }: Props) {
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
        <div className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          DAGs
        </div>
        <nav className="flex flex-col gap-0.5">
          {dags.map((d) => (
            <button
              key={d.dag_id}
              onClick={() => onSelect(d.dag_id)}
              className={cn(
                "flex items-center rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                selected === d.dag_id
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <span className="truncate font-mono text-xs">{d.dag_id}</span>
            </button>
          ))}
        </nav>
      </div>

      <div className="border-t p-3 text-[11px] text-muted-foreground">
        Auto-syncs from Airflow every 2 min
      </div>
    </aside>
  );
}
