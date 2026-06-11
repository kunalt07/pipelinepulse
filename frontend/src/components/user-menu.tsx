"use client";

import { useEffect, useRef, useState } from "react";
import { LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { cn } from "@/lib/utils";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

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

  if (!user) return null;

  const label = user.name || user.email;
  const initial = (label[0] ?? "?").toUpperCase();

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-full border border-border bg-background text-[11px] font-bold uppercase transition-colors",
          "hover:bg-accent",
        )}
        aria-label={`Account: ${label}`}
        title={label}
      >
        {initial}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-border bg-card p-1 shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <UserIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold">{user.name || "Account"}</div>
              <div className="truncate text-[11px] text-muted-foreground">{user.email}</div>
            </div>
            {user.is_admin && (
              <span className="rounded-full bg-brand/10 px-1.5 py-0.5 text-[9px] font-bold text-brand">
                ADMIN
              </span>
            )}
          </div>
          <button
            onClick={() => {
              setOpen(false);
              void logout();
            }}
            className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
