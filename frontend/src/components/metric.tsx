"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { AnimatedNumber } from "@/components/animated-number";
import { Sparkline } from "@/components/sparkline";

type Tone = "default" | "success" | "danger" | "warning" | "brand";

type Props = {
  label: string;
  value: number;
  decimals?: number;
  suffix?: string;
  hint?: string;
  tone?: Tone;
  spark?: number[];
  delay?: number;
};

const ACCENT_BORDER: Record<Tone, string> = {
  default: "before:bg-transparent",
  success: "before:bg-success",
  danger: "before:bg-danger",
  warning: "before:bg-warning",
  brand: "before:bg-brand",
};

const VALUE_COLOR: Record<Tone, string> = {
  default: "text-foreground",
  success: "text-success",
  danger: "text-danger",
  warning: "text-warning",
  brand: "text-brand",
};

const SPARK_COLOR: Record<Tone, string> = {
  default: "hsl(var(--muted-foreground))",
  success: "hsl(var(--success))",
  danger: "hsl(var(--danger))",
  warning: "hsl(var(--warning))",
  brand: "hsl(var(--brand))",
};

export function Metric({
  label,
  value,
  decimals = 0,
  suffix = "",
  hint,
  tone = "default",
  spark,
  delay = 0,
}: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "relative overflow-hidden rounded-lg border border-border bg-card p-5 shadow-sm",
        "before:absolute before:left-0 before:top-0 before:h-full before:w-[3px]",
        ACCENT_BORDER[tone],
      )}
    >
      <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-3 text-[2.5rem] font-bold tracking-tight leading-none", VALUE_COLOR[tone])}>
        <AnimatedNumber value={value} decimals={decimals} suffix={suffix} />
      </div>
      <div className="mt-3 flex items-end justify-between">
        {hint && <div className="text-xs font-medium text-muted-foreground">{hint}</div>}
        {spark && spark.length > 1 && (
          <div className="ml-auto">
            <Sparkline values={spark} color={SPARK_COLOR[tone]} width={70} height={20} />
          </div>
        )}
      </div>
    </motion.div>
  );
}
