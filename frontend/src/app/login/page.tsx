"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.authLogin(email.trim(), password);
      // Hard nav so the AuthProvider re-runs and the dashboard mounts cleanly.
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm space-y-5">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-brand text-brand-foreground">
            <Activity className="h-4 w-4" />
          </span>
          <span className="text-base font-bold tracking-tight">PipelinePulse</span>
        </div>

        <div>
          <h1 className="text-xl font-bold tracking-tight">Sign in</h1>
          <p className="mt-1 text-xs font-medium text-muted-foreground">
            Welcome back. Use your email and password.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Email
            </span>
            <input
              type="text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              className="h-9 w-full rounded-md border border-border bg-background px-3 font-mono text-xs"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Password
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="h-9 w-full rounded-md border border-border bg-background px-3 font-mono text-xs"
            />
          </label>

          {error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
              {error}
            </div>
          )}

          <Button type="submit" disabled={busy || !email.trim() || !password} className="w-full">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Sign in
          </Button>
        </form>

        <p className="text-center text-xs font-medium text-muted-foreground">
          No account yet?{" "}
          <Link href="/signup" className="font-semibold text-brand hover:underline">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
