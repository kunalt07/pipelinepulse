"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.authSignup(email.trim(), password, name.trim() || undefined);
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Signup failed");
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
          <h1 className="text-xl font-bold tracking-tight">Create your account</h1>
          <p className="mt-1 text-xs font-medium text-muted-foreground">
            The first account on this instance becomes the admin.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <label className="block space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Email
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              required
              className="h-9 w-full rounded-md border border-border bg-background px-3 font-mono text-xs"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Name <span className="font-medium normal-case tracking-normal text-muted-foreground/60">(optional)</span>
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              className="h-9 w-full rounded-md border border-border bg-background px-3 text-xs"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Password <span className="font-medium normal-case tracking-normal text-muted-foreground/60">(min 8 characters)</span>
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
              className="h-9 w-full rounded-md border border-border bg-background px-3 font-mono text-xs"
            />
          </label>

          {error && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
              {error}
            </div>
          )}

          <Button type="submit" disabled={busy || !email.trim() || password.length < 8} className="w-full">
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Create account
          </Button>
        </form>

        <p className="text-center text-xs font-medium text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-brand hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
