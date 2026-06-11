"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Loader2,
  Moon,
  RefreshCw,
  Sun,
  Webhook,
  X,
} from "lucide-react";
import {
  api,
  type SecretSetting,
  type Settings,
  type SettingsUpdate,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/theme-provider";
import { EnvironmentsCard } from "@/components/environments-card";
import { cn } from "@/lib/utils";

const cardEntry = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const },
};

type SaveState = "idle" | "saving" | "saved" | "error";

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === "saving") return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
  if (state === "saved") return <Check className="h-3.5 w-3.5 text-success" />;
  if (state === "error") return <span className="text-[10px] font-semibold text-danger">save failed</span>;
  return null;
}

function useDebouncedSaver() {
  const [save, setSave] = useState<SaveState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const trigger = (fn: () => Promise<unknown>, delay = 500) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      setSave("saving");
      try {
        await fn();
        setSave("saved");
        setTimeout(() => setSave("idle"), 1500);
      } catch {
        setSave("error");
        setTimeout(() => setSave("idle"), 3000);
      }
    }, delay);
  };

  return { save, trigger };
}

function SecretInput({
  label,
  hint,
  secret,
  placeholder,
  onSave,
  onClear,
}: {
  label: string;
  hint?: string;
  secret: SecretSetting;
  placeholder: string;
  onSave: (value: string) => Promise<void>;
  onClear: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(!secret.set);
  const [draft, setDraft] = useState("");
  const [reveal, setReveal] = useState(false);
  const [save, setSave] = useState<SaveState>("idle");

  useEffect(() => {
    if (!secret.set) setEditing(true);
  }, [secret.set]);

  const persist = async () => {
    if (!draft.trim()) return;
    setSave("saving");
    try {
      await onSave(draft.trim());
      setSave("saved");
      setDraft("");
      setEditing(false);
      setTimeout(() => setSave("idle"), 1500);
    } catch {
      setSave("error");
      setTimeout(() => setSave("idle"), 3000);
    }
  };

  const clear = async () => {
    setSave("saving");
    try {
      await onClear();
      setSave("saved");
      setEditing(true);
      setTimeout(() => setSave("idle"), 1500);
    } catch {
      setSave("error");
      setTimeout(() => setSave("idle"), 3000);
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
          {label}
          {secret.db_override && (
            <span className="ml-2 rounded-full bg-brand/10 px-1.5 py-0.5 text-[9px] font-bold normal-case tracking-normal text-brand">
              UI override
            </span>
          )}
        </span>
        <SaveIndicator state={save} />
      </div>

      {!editing && secret.set ? (
        <div className="flex items-center gap-2">
          <div className="flex-1 select-none rounded-md border border-border bg-muted/40 px-3 py-1.5 font-mono text-xs text-muted-foreground">
            ••••••••••••
          </div>
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            Replace
          </Button>
          <Button variant="outline" size="sm" onClick={clear}>
            <X className="h-3 w-3" />
            Clear
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type={reveal ? "text" : "password"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") persist();
                if (e.key === "Escape" && secret.set) {
                  setDraft("");
                  setEditing(false);
                }
              }}
              placeholder={placeholder}
              className="h-8 w-full rounded-md border border-border bg-background px-3 pr-8 font-mono text-xs"
              autoFocus
            />
            <button
              onClick={() => setReveal((r) => !r)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={reveal ? "Hide" : "Show"}
            >
              {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
          <Button variant="default" size="sm" onClick={persist} disabled={!draft.trim()}>
            Save
          </Button>
          {secret.set && (
            <Button variant="ghost" size="sm" onClick={() => { setDraft(""); setEditing(false); }}>
              Cancel
            </Button>
          )}
        </div>
      )}
      {hint && <p className="text-[11px] font-medium text-muted-foreground">{hint}</p>}
    </div>
  );
}

function NumberSetting({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  suffix,
  onSave,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  onSave: (n: number) => Promise<void>;
}) {
  const [draft, setDraft] = useState<number>(value);
  const { save, trigger } = useDebouncedSaver();

  useEffect(() => setDraft(value), [value]);

  const persist = (next: number) => {
    const clamped = Math.max(min, Math.min(max, next));
    setDraft(clamped);
    trigger(() => onSave(clamped));
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
        <SaveIndicator state={save} />
      </div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={draft}
          min={min}
          max={max}
          step={step}
          onChange={(e) => persist(Number(e.target.value) || min)}
          className="h-8 w-24 rounded-md border border-border bg-background px-2 text-center font-mono text-xs"
        />
        {suffix && <span className="text-xs font-medium text-muted-foreground">{suffix}</span>}
      </div>
      {hint && <p className="text-[11px] font-medium text-muted-foreground">{hint}</p>}
    </div>
  );
}

function IntegrationsCard({
  settings,
  apply,
  reload,
}: {
  settings: Settings;
  apply: (body: SettingsUpdate) => Promise<void>;
  reload: () => Promise<void>;
}) {
  const [model, setModel] = useState(settings.gemini_model);
  const { save, trigger } = useDebouncedSaver();

  useEffect(() => setModel(settings.gemini_model), [settings.gemini_model]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Webhook className="h-4 w-4 text-muted-foreground" />
          Integrations
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          Webhook + AI credentials. UI values override env vars at runtime.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        <SecretInput
          label="Webhook URL"
          hint="Slack, Discord, Mattermost, etc. Used for failure alerts and scheduled report notifications."
          secret={settings.webhook_url}
          placeholder="https://hooks.slack.com/services/..."
          onSave={async (v) => {
            await apply({ webhook_url: v });
            await reload();
          }}
          onClear={async () => {
            await apply({ webhook_url: null });
            await reload();
          }}
        />

        <SecretInput
          label="Gemini API key"
          hint="Required for AI failure analysis and report narratives. Stored in DB plaintext — fine for self-hosted."
          secret={settings.gemini_api_key}
          placeholder="AIza..."
          onSave={async (v) => {
            await apply({ gemini_api_key: v });
            await reload();
          }}
          onClear={async () => {
            await apply({ gemini_api_key: null });
            await reload();
          }}
        />

        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
              Gemini model
            </span>
            <SaveIndicator state={save} />
          </div>
          <input
            type="text"
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              trigger(() => apply({ gemini_model: e.target.value }));
            }}
            className="h-8 w-full max-w-sm rounded-md border border-border bg-background px-3 font-mono text-xs"
            placeholder="gemini-flash-lite-latest"
          />
          <p className="text-[11px] font-medium text-muted-foreground">
            Default: <code className="font-mono">gemini-flash-lite-latest</code> (works on free tier).
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function SyncCard({
  settings,
  apply,
}: {
  settings: Settings;
  apply: (body: SettingsUpdate) => Promise<void>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <RefreshCw className="h-4 w-4 text-muted-foreground" />
          Sync
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          How often PipelinePulse polls Airflow for new runs.
        </p>
      </CardHeader>
      <CardContent>
        <NumberSetting
          label="Sync interval"
          value={settings.sync_interval_minutes}
          min={1}
          max={60}
          suffix="minutes"
          hint="Lower = fresher data + more Airflow API load. Reschedules immediately on save."
          onSave={(n) => apply({ sync_interval_minutes: n })}
        />
      </CardContent>
    </Card>
  );
}

function StuckCard({
  settings,
  apply,
}: {
  settings: Settings;
  apply: (body: SettingsUpdate) => Promise<void>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          Stuck-run detection
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          A run is flagged as stuck when its elapsed time exceeds <code>multiplier × p95</code> of
          past successes (or the floor, whichever is larger).
        </p>
      </CardHeader>
      <CardContent className="grid gap-5 sm:grid-cols-3">
        <NumberSetting
          label="Multiplier"
          value={settings.stuck_multiplier}
          min={1.5}
          max={10}
          step={0.5}
          suffix="× p95"
          onSave={(n) => apply({ stuck_multiplier: n })}
        />
        <NumberSetting
          label="Floor"
          value={settings.stuck_floor_seconds}
          min={30}
          max={600}
          step={10}
          suffix="seconds"
          hint="Don't flag faster than this."
          onSave={(n) => apply({ stuck_floor_seconds: n })}
        />
        <NumberSetting
          label="Min history"
          value={settings.stuck_min_history}
          min={3}
          max={20}
          suffix="successes"
          hint="Need this many past successes before computing p95."
          onSave={(n) => apply({ stuck_min_history: n })}
        />
      </CardContent>
    </Card>
  );
}

function ThemeCard() {
  const { theme, toggle } = useTheme();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <p className="text-xs font-medium text-muted-foreground">Saved locally to this browser.</p>
      </CardHeader>
      <CardContent>
        <div className="flex gap-1 rounded-md border border-border bg-background/50 p-0.5">
          {(["light", "dark"] as const).map((t) => {
            const active = theme === t;
            const Icon = t === "dark" ? Moon : Sun;
            return (
              <button
                key={t}
                onClick={() => {
                  if (theme !== t) toggle();
                }}
                className={cn(
                  "flex items-center gap-1.5 rounded px-3 py-1 text-xs font-semibold capitalize transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t}
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function DangerAction({
  title,
  description,
  buttonLabel,
  onConfirm,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  onConfirm: () => Promise<{ message: string }>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setConfirming(false);
    setConfirmText("");
  };

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await onConfirm();
      setResult(r.message);
      reset();
      setTimeout(() => setResult(null), 6000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
      setTimeout(() => setError(null), 6000);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-danger/30 bg-danger/[0.03] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{title}</div>
          <p className="text-xs font-medium text-muted-foreground">{description}</p>
        </div>
        {!confirming && !result && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirming(true)}
            className="shrink-0 border-danger/40 text-danger hover:bg-danger/10"
          >
            {buttonLabel}
          </Button>
        )}
      </div>
      {confirming && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className="text-[11px] font-medium text-muted-foreground">
            Type <code className="rounded bg-muted px-1 font-mono">DELETE</code> to confirm:
          </span>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="h-7 w-32 rounded border border-border bg-background px-2 font-mono text-xs"
            autoFocus
          />
          <Button
            variant="outline"
            size="sm"
            onClick={run}
            disabled={confirmText !== "DELETE" || running}
            className="border-danger/40 text-danger hover:bg-danger/10"
          >
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirm"}
          </Button>
          <Button variant="ghost" size="sm" onClick={reset}>
            Cancel
          </Button>
        </div>
      )}
      {result && (
        <div className="rounded-md border border-success/30 bg-success/5 px-3 py-1.5 text-xs font-medium text-success">
          {result}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-1.5 text-xs font-medium text-danger">
          {error}
        </div>
      )}
    </div>
  );
}

function DangerCard() {
  return (
    <Card className="border-danger/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-danger">
          <AlertTriangle className="h-4 w-4" />
          Danger zone
        </CardTitle>
        <p className="text-xs font-medium text-muted-foreground">
          Each action is irreversible. Type <code>DELETE</code> to confirm.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <DangerAction
          title="Reset all per-DAG alert configs"
          description="Removes mute, threshold, and quiet-hour overrides for every DAG."
          buttonLabel="Reset"
          onConfirm={async () => {
            const r = await api.dangerResetAlertConfigs();
            return { message: `Removed ${r.deleted} alert config${r.deleted === 1 ? "" : "s"}.` };
          }}
        />
        <DangerAction
          title="Clear notifications history"
          description="Deletes the local record of webhook deliveries. Won't replay alerts already sent."
          buttonLabel="Clear"
          onConfirm={async () => {
            const r = await api.dangerClearNotifications();
            return { message: `Cleared ${r.deleted} notification${r.deleted === 1 ? "" : "s"}.` };
          }}
        />
        <DangerAction
          title="Clear report history"
          description="Deletes saved report snapshots. Existing scheduled config is kept."
          buttonLabel="Clear"
          onConfirm={async () => {
            const r = await api.dangerClearReports();
            return { message: `Cleared ${r.deleted} report${r.deleted === 1 ? "" : "s"}.` };
          }}
        />
        <DangerAction
          title="Force full re-sync from Airflow"
          description="Truncates dag_runs + task_instances and re-pulls from Airflow. May take 30+ seconds."
          buttonLabel="Re-sync"
          onConfirm={async () => {
            const r = await api.dangerFullResync();
            return {
              message: `Re-synced — deleted ${r.runs_deleted} runs / ${r.tasks_deleted} tasks; pulled ${r.runs_pulled}.`,
            };
          }}
        />
      </CardContent>
    </Card>
  );
}

export function SettingsView() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const s = await api.getSettings();
      setSettings(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const apply = async (body: SettingsUpdate) => {
    const next = await api.updateSettings(body);
    setSettings(next);
  };

  if (error) {
    return (
      <div className="p-6">
        <p className="text-sm text-danger">{error}</p>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="space-y-3 p-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-32 rounded-lg shimmer" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">Settings</h2>
        <p className="text-xs font-medium text-muted-foreground">
          Configure PipelinePulse without restarting. Changes apply within a few seconds.
        </p>
      </div>

      <motion.div {...cardEntry}>
        <IntegrationsCard settings={settings} apply={apply} reload={reload} />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.05 }}>
        <SyncCard settings={settings} apply={apply} />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.1 }}>
        <StuckCard settings={settings} apply={apply} />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.15 }}>
        <EnvironmentsCard />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.2 }}>
        <ThemeCard />
      </motion.div>

      <motion.div {...cardEntry} transition={{ ...cardEntry.transition, delay: 0.25 }}>
        <DangerCard />
      </motion.div>
    </div>
  );
}
