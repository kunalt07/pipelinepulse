import { cn } from "@/lib/utils";

const STATE_STYLES: Record<string, string> = {
  success: "bg-success/10 text-success border-success/20",
  failed: "bg-danger/10 text-danger border-danger/20",
  running: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  queued: "bg-muted text-muted-foreground border-border",
};

export function StatusPill({ state, className }: { state: string; className?: string }) {
  const style = STATE_STYLES[state] ?? STATE_STYLES.queued;
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium capitalize",
        style,
        className,
      )}
    >
      <span
        className={cn("mr-1.5 h-1.5 w-1.5 rounded-full", {
          "bg-success": state === "success",
          "bg-danger": state === "failed",
          "bg-blue-500 animate-pulse": state === "running",
          "bg-muted-foreground": !["success", "failed", "running"].includes(state),
        })}
      />
      {state}
    </span>
  );
}
