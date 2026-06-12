"use client";

import { useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  Edit2,
  Loader2,
  Plus,
  Server,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, type EnvironmentInfo } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type EditingState =
  | { mode: "create" }
  | { mode: "edit"; id: number; original: EnvironmentInfo }
  | null;

type FormState = {
  name: string;
  airflow_base_url: string;
  airflow_username: string;
  airflow_password: string;
  airflow_public_url: string;
  is_default: boolean;
  enabled: boolean;
  changePassword: boolean; // when editing: only send password if user toggled this
};

const EMPTY_FORM: FormState = {
  name: "",
  airflow_base_url: "",
  airflow_username: "",
  airflow_password: "",
  airflow_public_url: "",
  is_default: false,
  enabled: true,
  changePassword: true,
};

function fromInfo(info: EnvironmentInfo): FormState {
  return {
    name: info.name,
    airflow_base_url: info.airflow_base_url,
    airflow_username: info.airflow_username ?? "",
    airflow_password: "",
    airflow_public_url: info.airflow_public_url ?? "",
    is_default: info.is_default,
    enabled: info.enabled,
    changePassword: false,
  };
}

export function EnvironmentsCard() {
  const [envs, setEnvs] = useState<EnvironmentInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditingState>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; latency_ms: number; error?: string }>>({});
  const [testing, setTesting] = useState<number | null>(null);

  const reload = async () => {
    try {
      const items = await api.listEnvironments();
      setEnvs(items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load environments");
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const startCreate = () => {
    setForm(EMPTY_FORM);
    setEditing({ mode: "create" });
  };

  const startEdit = (info: EnvironmentInfo) => {
    setForm(fromInfo(info));
    setEditing({ mode: "edit", id: info.id, original: info });
  };

  const cancel = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
  };

  const submit = async () => {
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      if (editing.mode === "create") {
        await api.createEnvironment({
          name: form.name.trim(),
          airflow_base_url: form.airflow_base_url.trim(),
          airflow_username: form.airflow_username.trim() || null,
          airflow_password: form.airflow_password.trim() || null,
          airflow_public_url: form.airflow_public_url.trim() || null,
          is_default: form.is_default,
          enabled: form.enabled,
        });
      } else {
        await api.updateEnvironment(editing.id, {
          name: form.name.trim(),
          airflow_base_url: form.airflow_base_url.trim(),
          airflow_username: form.airflow_username.trim() || null,
          ...(form.changePassword
            ? form.airflow_password.trim()
              ? { airflow_password: form.airflow_password.trim() }
              : { clear_password: true }
            : {}),
          airflow_public_url: form.airflow_public_url.trim() || null,
          is_default: form.is_default || undefined,
          enabled: form.enabled,
        });
      }
      await reload();
      cancel();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (id: number) => {
    if (!confirm("Delete this environment? This cannot be undone.")) return;
    setError(null);
    try {
      await api.deleteEnvironment(id);
      await reload();
      return;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      // Backend refuses cascadeless delete on envs with run history; offer cascade.
      if (msg.toLowerCase().includes("cascade=true")) {
        const cascadeOk = confirm(
          "This environment has run history (runs, tasks, alerts, SLAs, reports, " +
            "annotations).\n\n" +
            "Delete the environment AND all its scoped data? This cannot be undone.",
        );
        if (!cascadeOk) {
          setError("Delete cancelled.");
          return;
        }
        try {
          await api.deleteEnvironment(id, { cascade: true });
          await reload();
          return;
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Cascade delete failed");
          return;
        }
      }
      setError(msg);
    }
  };

  const onTest = async (id: number) => {
    setTesting(id);
    try {
      const r = await api.testEnvironment(id);
      setTestResults((prev) => ({ ...prev, [id]: r }));
      setTimeout(() => {
        setTestResults((prev) => {
          const { [id]: _drop, ...rest } = prev;
          return rest;
        });
      }, 6000);
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: false, latency_ms: 0, error: e instanceof Error ? e.message : "Failed" },
      }));
    } finally {
      setTesting(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Server className="h-4 w-4 text-muted-foreground" />
          Environments
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          Connect multiple Airflow instances. The active environment is selected from the
          sidebar dropdown and applies to all views.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
            {error}
          </div>
        )}

        {envs === null ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <div key={i} className="h-12 rounded shimmer" />
            ))}
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border border-border">
            <div className="grid grid-cols-[1fr_2fr_auto_auto] gap-3 border-b border-border bg-muted/30 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
              <div>Name</div>
              <div>Base URL</div>
              <div>Status</div>
              <div className="w-28 text-right">Actions</div>
            </div>
            {envs.map((e) => {
              const result = testResults[e.id];
              return (
                <div
                  key={e.id}
                  className={cn(
                    "grid grid-cols-[1fr_2fr_auto_auto] items-center gap-3 border-b border-border/40 px-4 py-2.5 text-xs last:border-b-0",
                    !e.enabled && "opacity-60",
                  )}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-mono text-[12px] font-semibold">{e.name}</span>
                      {e.is_default && (
                        <span className="rounded-full bg-brand/10 px-1.5 py-0.5 text-[9px] font-bold text-brand">
                          DEFAULT
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] font-medium text-muted-foreground/80">
                      {e.password_set ? "auth set" : "no auth"} · {e.enabled ? "enabled" : "disabled"}
                    </div>
                  </div>
                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                    {e.airflow_base_url}
                  </div>
                  <div className="flex items-center gap-1.5">
                    {testing === e.id && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                    )}
                    {result && result.ok && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-success">
                        <CheckCircle2 className="h-3 w-3" />
                        {result.latency_ms}ms
                      </span>
                    )}
                    {result && !result.ok && (
                      <span
                        className="flex items-center gap-1 text-[11px] font-semibold text-danger"
                        title={result.error}
                      >
                        <XCircle className="h-3 w-3" />
                        failed
                      </span>
                    )}
                  </div>
                  <div className="flex items-center justify-end gap-1">
                    <Button variant="outline" size="sm" onClick={() => onTest(e.id)} disabled={testing === e.id}>
                      Test
                    </Button>
                    <button
                      onClick={() => startEdit(e)}
                      className="rounded border border-border p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                      aria-label={`Edit ${e.name}`}
                    >
                      <Edit2 className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => onDelete(e.id)}
                      disabled={e.is_default}
                      className="rounded border border-border p-1.5 text-muted-foreground hover:border-danger/40 hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-30"
                      aria-label={`Delete ${e.name}`}
                      title={e.is_default ? "Cannot delete the default environment" : `Delete ${e.name}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!editing && (
          <Button variant="outline" size="sm" onClick={startCreate}>
            <Plus className="h-3.5 w-3.5" />
            Add environment
          </Button>
        )}

        {editing && (
          <div className="space-y-3 rounded-md border border-border bg-muted/20 p-4">
            <div className="text-sm font-semibold">
              {editing.mode === "create" ? "New environment" : `Edit ${editing.original.name}`}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Name" hint="alphanumeric, _, -">
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="prod"
                  className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
                />
              </Field>

              <Field label="Airflow base URL">
                <input
                  type="text"
                  value={form.airflow_base_url}
                  onChange={(e) => setForm({ ...form, airflow_base_url: e.target.value })}
                  placeholder="https://airflow.example.com"
                  className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
                />
              </Field>

              <Field label="Username">
                <input
                  type="text"
                  value={form.airflow_username}
                  onChange={(e) => setForm({ ...form, airflow_username: e.target.value })}
                  placeholder="admin"
                  className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
                />
              </Field>

              <Field label="Password" hint={editing.mode === "edit" && !form.changePassword ? "kept (uncheck to clear)" : undefined}>
                {editing.mode === "edit" && (
                  <label className="mb-1 flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={form.changePassword}
                      onChange={(e) => setForm({ ...form, changePassword: e.target.checked })}
                      className="h-3 w-3"
                    />
                    Change password
                  </label>
                )}
                <input
                  type="password"
                  value={form.airflow_password}
                  onChange={(e) => setForm({ ...form, airflow_password: e.target.value })}
                  disabled={editing.mode === "edit" && !form.changePassword}
                  placeholder={editing.mode === "edit" ? "leave blank to clear" : "••••"}
                  className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs disabled:opacity-40"
                />
              </Field>

              <Field label="Public URL (optional)" hint="for webhook deep-links">
                <input
                  type="text"
                  value={form.airflow_public_url}
                  onChange={(e) => setForm({ ...form, airflow_public_url: e.target.value })}
                  placeholder="https://airflow.example.com"
                  className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
                />
              </Field>

              <div className="flex flex-col gap-2 self-end pb-1">
                <label className="flex items-center gap-2 text-xs font-medium">
                  <input
                    type="checkbox"
                    checked={form.is_default}
                    onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                    className="h-3.5 w-3.5"
                  />
                  Set as default
                </label>
                <label className="flex items-center gap-2 text-xs font-medium">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    className="h-3.5 w-3.5"
                  />
                  Enabled (sync runs)
                </label>
              </div>
            </div>

            <div className="flex items-center gap-2 border-t border-border pt-3">
              <Button variant="default" size="sm" onClick={submit} disabled={busy || !form.name.trim() || !form.airflow_base_url.trim()}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                {editing.mode === "create" ? "Create" : "Save"}
              </Button>
              <Button variant="ghost" size="sm" onClick={cancel} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-bold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
        {hint && <span className="ml-1 normal-case tracking-normal text-muted-foreground/60">— {hint}</span>}
      </span>
      {children}
    </label>
  );
}
