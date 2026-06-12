"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Key, Loader2, Plus, Trash2 } from "lucide-react";
import { api, type ApiTokenInfo, type NewApiToken } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CreatingState =
  | { mode: "form"; name: string }
  | { mode: "reveal"; token: NewApiToken; copied: boolean }
  | null;

export function ApiTokensCard() {
  const [tokens, setTokens] = useState<ApiTokenInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<CreatingState>(null);
  const [busy, setBusy] = useState(false);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState<{ id: number; text: string } | null>(null);

  const reload = async () => {
    try {
      const items = await api.listApiTokens();
      setTokens(items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tokens");
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const startCreate = () => {
    setCreating({ mode: "form", name: "" });
    setError(null);
  };

  const submitCreate = async () => {
    if (creating?.mode !== "form" || !creating.name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const token = await api.createApiToken(creating.name.trim());
      setCreating({ mode: "reveal", token, copied: false });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  const copyToken = async () => {
    if (creating?.mode !== "reveal") return;
    try {
      await navigator.clipboard.writeText(creating.token.plaintext);
      setCreating({ ...creating, copied: true });
      setTimeout(() => {
        // Reset the "Copied!" indicator if the dialog is still open
        setCreating((c) => (c?.mode === "reveal" ? { ...c, copied: false } : c));
      }, 2000);
    } catch {
      // Clipboard API can fail in unusual contexts (no HTTPS, etc.); user can manually select.
    }
  };

  const finishReveal = () => {
    setCreating(null);
  };

  const askRevoke = (id: number) => {
    setRevokeConfirm({ id, text: "" });
  };

  const confirmRevoke = async () => {
    if (!revokeConfirm || revokeConfirm.text !== "DELETE") return;
    setRevokingId(revokeConfirm.id);
    setError(null);
    try {
      await api.revokeApiToken(revokeConfirm.id);
      setRevokeConfirm(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Revoke failed");
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Key className="h-4 w-4 text-muted-foreground" />
          API tokens
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          Personal access tokens for curl/scripts. Send as{" "}
          <code className="rounded bg-muted px-1 font-mono text-[11px]">Authorization: Bearer pp_…</code>
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
            {error}
          </div>
        )}

        {tokens === null ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <div key={i} className="h-10 rounded shimmer" />
            ))}
          </div>
        ) : tokens.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            No tokens yet. Create one to authenticate from scripts.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border border-border">
            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-3 border-b border-border bg-muted/30 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              <div>Name</div>
              <div>Prefix</div>
              <div>Created</div>
              <div>Last used</div>
              <div className="w-8" />
            </div>
            {tokens.map((t) => (
              <div
                key={t.id}
                className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-3 border-b border-border/40 px-4 py-2.5 text-xs last:border-b-0"
              >
                <div className="truncate font-mono font-semibold">{t.name}</div>
                <div className="font-mono text-[11px] text-muted-foreground">{t.token_prefix}…</div>
                <div className="text-[11px] text-muted-foreground">
                  {t.created_at ? t.created_at.split(".")[0] : "—"}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {t.last_used_at ? t.last_used_at.split(".")[0] : "never"}
                </div>
                <button
                  onClick={() => askRevoke(t.id)}
                  disabled={revokingId === t.id}
                  className="rounded border border-border p-1.5 text-muted-foreground hover:border-danger/40 hover:bg-danger/10 hover:text-danger disabled:opacity-30"
                  aria-label={`Revoke ${t.name}`}
                >
                  {revokingId === t.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3" />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}

        {revokeConfirm && (
          <div className="space-y-2 rounded-md border border-danger/30 bg-danger/5 p-3 text-xs">
            <div className="font-medium">
              Revoke this token? Any scripts using it will stop working.
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground">
                Type <code className="rounded bg-muted px-1 font-mono">DELETE</code> to confirm:
              </span>
              <input
                type="text"
                value={revokeConfirm.text}
                onChange={(e) => setRevokeConfirm({ ...revokeConfirm, text: e.target.value })}
                className="h-7 w-32 rounded border border-border bg-background px-2 font-mono text-xs"
                autoFocus
              />
              <Button
                variant="outline"
                size="sm"
                onClick={confirmRevoke}
                disabled={revokeConfirm.text !== "DELETE"}
                className="border-danger/40 text-danger hover:bg-danger/10"
              >
                Confirm
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setRevokeConfirm(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {!creating && !revokeConfirm && (
          <Button variant="outline" size="sm" onClick={startCreate}>
            <Plus className="h-3.5 w-3.5" />
            Create token
          </Button>
        )}

        {creating?.mode === "form" && (
          <div className="space-y-3 rounded-md border border-border bg-muted/20 p-4">
            <div className="text-sm font-semibold">New token</div>
            <label className="flex flex-col gap-1 text-xs">
              <span className="font-bold uppercase tracking-[0.12em] text-muted-foreground">
                Name
                <span className="ml-1 normal-case tracking-normal text-muted-foreground/60">
                  — what's this for?
                </span>
              </span>
              <input
                type="text"
                value={creating.name}
                onChange={(e) => setCreating({ mode: "form", name: e.target.value })}
                placeholder="deploy-bot"
                autoFocus
                className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
              />
            </label>
            <div className="flex items-center gap-2 border-t border-border pt-2">
              <Button
                size="sm"
                onClick={submitCreate}
                disabled={busy || !creating.name.trim()}
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Create
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setCreating(null)} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {creating?.mode === "reveal" && (
          <div className="space-y-3 rounded-md border border-warning/40 bg-warning/5 p-4">
            <div className="text-sm font-semibold">Save this token now</div>
            <p className="text-xs font-medium text-muted-foreground">
              This is the only time you&apos;ll see the full token. Copy it and store it
              somewhere safe — you can&apos;t retrieve it later.
            </p>
            <div className="flex items-center gap-2">
              <code
                className={cn(
                  "block min-w-0 flex-1 select-all overflow-x-auto rounded border border-border bg-background px-3 py-2 font-mono text-xs",
                )}
              >
                {creating.token.plaintext}
              </code>
              <Button variant="outline" size="sm" onClick={copyToken}>
                {creating.copied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-success" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    Copy
                  </>
                )}
              </Button>
            </div>
            <Button variant="default" size="sm" onClick={finishReveal}>
              I&apos;ve saved it
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
