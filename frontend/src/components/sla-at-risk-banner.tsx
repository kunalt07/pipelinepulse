"use client";

import { motion } from "framer-motion";
import { Clock } from "lucide-react";
import type { SlaAtRisk } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

type Props = {
  items: SlaAtRisk[];
  onSelect: (dagId: string) => void;
};

export function SlaAtRiskBanner({ items, onSelect }: Props) {
  if (items.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
    >
      <Card className="overflow-hidden border-amber-500/40 bg-amber-500/5">
        <CardContent className="space-y-2 p-4">
          <div className="flex items-center gap-2 text-amber-500">
            <motion.span
              animate={{ scale: [1, 1.15, 1], opacity: [0.7, 1, 0.7] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            >
              <Clock className="h-4 w-4" />
            </motion.span>
            <span className="text-sm font-bold">
              {items.length === 1 ? "1 DAG at risk" : `${items.length} DAGs at risk`}
            </span>
            <span className="text-[11px] font-medium text-muted-foreground">
              SLA deadline approaching
            </span>
          </div>
          <ul className="space-y-1.5 text-xs">
            {items.map((s) => (
              <li
                key={s.dag_id}
                className="flex cursor-pointer items-center justify-between rounded px-2 py-1 hover:bg-amber-500/10"
                onClick={() => onSelect(s.dag_id)}
              >
                <span className="font-mono text-[12px] font-semibold">{s.dag_id}</span>
                <span className="text-[11px] font-medium text-muted-foreground">{s.reason}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </motion.div>
  );
}
