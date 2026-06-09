"use client";

import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatDuration } from "@/lib/utils";
import type { StuckRun } from "@/lib/api";

type Props = {
  stuck: StuckRun[];
  onSelect: (dagId: string, runId: string) => void;
};

export function StuckRunsBanner({ stuck, onSelect }: Props) {
  if (stuck.length === 0) return null;

  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center gap-2 text-amber-500">
          <AlertTriangle className="h-4 w-4" />
          <span className="text-sm font-medium">
            {stuck.length === 1 ? "1 stuck run" : `${stuck.length} stuck runs`}
          </span>
          <span className="text-[11px] text-muted-foreground">
            running &gt; 2× p95
          </span>
        </div>
        <ul className="space-y-1.5 text-xs">
          {stuck.map((s) => (
            <li
              key={`${s.dag_id}/${s.run_id}`}
              className="flex cursor-pointer items-center justify-between rounded px-2 py-1 hover:bg-amber-500/10"
              onClick={() => onSelect(s.dag_id, s.run_id)}
            >
              <div className="flex min-w-0 flex-col">
                <span className="font-mono text-[12px]">{s.dag_id}</span>
                <span className="truncate font-mono text-[10px] text-muted-foreground">
                  {s.run_id}
                </span>
              </div>
              <div className="ml-3 shrink-0 text-right tabular-nums">
                <div className="text-amber-500">
                  {formatDuration(s.elapsed_seconds)} elapsed
                </div>
                <div className="text-[10px] text-muted-foreground">
                  threshold {formatDuration(s.threshold_seconds)} · p95{" "}
                  {formatDuration(s.p95_seconds)}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
