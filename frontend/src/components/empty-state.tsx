import type { LucideIcon } from "lucide-react";

type Props = {
  icon: LucideIcon;
  title: string;
  hint?: string;
  className?: string;
};

export function EmptyState({ icon: Icon, title, hint, className = "" }: Props) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 px-6 py-10 text-center ${className}`}>
      <div className="rounded-full border border-dashed border-border/70 p-3">
        <Icon className="h-5 w-5 text-muted-foreground/70" />
      </div>
      <div className="text-sm font-medium">{title}</div>
      {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
