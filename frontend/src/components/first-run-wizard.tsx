"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  ArrowRight,
  Bell,
  Check,
  CheckCircle2,
  Loader2,
  Server,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Step = "welcome" | "airflow" | "webhook" | "ai" | "done";

const STEPS: Step[] = ["welcome", "airflow", "webhook", "ai", "done"];

type ProbeState =
  | { kind: "idle" }
  | { kind: "probing" }
  | { kind: "ok"; latency?: number }
  | { kind: "err"; message: string };

type Summary = {
  airflowName: string;
  webhookConfigured: boolean;
  aiConfigured: boolean;
};

type Props = {
  onSkip: () => void;
  onComplete: () => void;
  /** When true, "Save and continue" buttons advance the step WITHOUT calling
   * any save APIs. Lets us walk through the UI on an already-set-up instance
   * (via ?wizard=preview) without touching the DB. */
  preview?: boolean;
};

export function FirstRunWizard({ onSkip, onComplete, preview = false }: Props) {
  const [step, setStep] = useState<Step>("welcome");
  const [summary, setSummary] = useState<Summary>({
    airflowName: "",
    webhookConfigured: false,
    aiConfigured: false,
  });

  const advance = (next: Step) => setStep(next);

  return (
    <div className="flex min-h-full flex-col items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <ProgressDots step={step} />

        <Card>
          <CardContent className="p-6">
            <AnimatePresence mode="wait">
              {step === "welcome" && (
                <StepFrame key="welcome">
                  <WelcomeStep
                    onContinue={() => advance("airflow")}
                    onSkip={onSkip}
                  />
                </StepFrame>
              )}
              {step === "airflow" && (
                <StepFrame key="airflow">
                  <AirflowStep
                    preview={preview}
                    onSaved={(name) => {
                      setSummary((s) => ({ ...s, airflowName: name }));
                      advance("webhook");
                    }}
                  />
                </StepFrame>
              )}
              {step === "webhook" && (
                <StepFrame key="webhook">
                  <WebhookStep
                    preview={preview}
                    onDone={(configured) => {
                      setSummary((s) => ({ ...s, webhookConfigured: configured }));
                      advance("ai");
                    }}
                  />
                </StepFrame>
              )}
              {step === "ai" && (
                <StepFrame key="ai">
                  <AIStep
                    preview={preview}
                    onDone={(configured) => {
                      setSummary((s) => ({ ...s, aiConfigured: configured }));
                      advance("done");
                    }}
                  />
                </StepFrame>
              )}
              {step === "done" && (
                <StepFrame key="done">
                  <DoneStep summary={summary} onOpen={onComplete} />
                </StepFrame>
              )}
            </AnimatePresence>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------- Layout helpers ----------

function ProgressDots({ step }: { step: Step }) {
  const idx = STEPS.indexOf(step);
  return (
    <div className="flex items-center justify-center gap-1.5">
      {STEPS.map((s, i) => (
        <div
          key={s}
          className={cn(
            "h-1.5 rounded-full transition-all",
            i === idx
              ? "w-8 bg-brand"
              : i < idx
                ? "w-1.5 bg-brand/60"
                : "w-1.5 bg-border",
          )}
        />
      ))}
    </div>
  );
}

function StepFrame({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

function FieldLabel({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
      {hint && (
        <span className="ml-1 normal-case tracking-normal text-muted-foreground/60">{hint}</span>
      )}
    </span>
  );
}

function ProbeBadge({ state }: { state: ProbeState }) {
  if (state.kind === "idle") return null;
  if (state.kind === "probing") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Testing…
      </span>
    );
  }
  if (state.kind === "ok") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-success">
        <CheckCircle2 className="h-3 w-3" />
        Connected{state.latency != null ? ` · ${state.latency}ms` : ""}
      </span>
    );
  }
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 truncate text-[11px] font-semibold text-danger"
      title={state.message}
    >
      <XCircle className="h-3 w-3 shrink-0" />
      {state.message}
    </span>
  );
}

// ---------- Step: Welcome ----------

function WelcomeStep({
  onContinue,
  onSkip,
}: {
  onContinue: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="space-y-4 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md bg-brand text-brand-foreground">
        <Activity className="h-6 w-6" />
      </div>
      <div className="space-y-2">
        <h1 className="text-lg font-bold tracking-tight">Welcome to PipelinePulse</h1>
        <p className="text-sm font-medium text-muted-foreground">
          A single pane of glass for your Airflow runs — history, alerts, SLA
          tracking, AI failure analysis, shareable reports. Self-hosted, yours.
        </p>
        <p className="text-xs font-medium text-muted-foreground">
          We&apos;ll connect your first Airflow and (optionally) wire up alerts
          and AI in the next few steps. Takes about a minute.
        </p>
      </div>
      <div className="flex flex-col items-stretch gap-2 pt-2">
        <Button onClick={onContinue} className="w-full">
          Get started
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
        <button
          onClick={onSkip}
          className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          Skip and explore Settings
        </button>
      </div>
    </div>
  );
}

// ---------- Step: Connect Airflow ----------

function AirflowStep({ preview, onSaved }: { preview: boolean; onSaved: (name: string) => void }) {
  const [name, setName] = useState("production");
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [probe, setProbe] = useState<ProbeState>({ kind: "idle" });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const valid = name.trim() && baseUrl.trim();
  const probed = probe.kind === "ok";

  const onTest = async () => {
    if (!baseUrl.trim()) return;
    setProbe({ kind: "probing" });
    try {
      const r = await api.probeAirflow({
        airflow_base_url: baseUrl.trim(),
        airflow_username: username.trim() || undefined,
        airflow_password: password || undefined,
      });
      if (r.ok) setProbe({ kind: "ok", latency: r.latency_ms });
      else setProbe({ kind: "err", message: r.error || "Connection failed" });
    } catch (e) {
      setProbe({
        kind: "err",
        message: e instanceof Error ? e.message : "Probe failed",
      });
    }
  };

  const onSave = async () => {
    setSaving(true);
    setSaveError(null);
    if (preview) {
      // Preview mode: skip the API call, just advance.
      onSaved(name.trim());
      return;
    }
    try {
      await api.createEnvironment({
        name: name.trim(),
        airflow_base_url: baseUrl.trim(),
        airflow_username: username.trim() || null,
        airflow_password: password || null,
        is_default: true,
        enabled: true,
      });
      onSaved(name.trim());
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Server className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-bold tracking-tight">Connect your Airflow</h2>
      </div>
      <p className="text-xs font-medium text-muted-foreground">
        We&apos;ll probe the REST API to make sure the URL and credentials work
        before saving.
      </p>

      <div className="space-y-3">
        <label className="flex flex-col gap-1">
          <FieldLabel>Name</FieldLabel>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="production"
            className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
          />
        </label>
        <label className="flex flex-col gap-1">
          <FieldLabel>Airflow base URL</FieldLabel>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => {
              setBaseUrl(e.target.value);
              setProbe({ kind: "idle" });
            }}
            placeholder="https://airflow.example.com"
            className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <FieldLabel>Username</FieldLabel>
            <input
              type="text"
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                setProbe({ kind: "idle" });
              }}
              placeholder="admin"
              className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
            />
          </label>
          <label className="flex flex-col gap-1">
            <FieldLabel>Password</FieldLabel>
            <input
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setProbe({ kind: "idle" });
              }}
              className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
            />
          </label>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onTest}
          disabled={!valid || probe.kind === "probing"}
        >
          Test connection
        </Button>
        <ProbeBadge state={probe} />
      </div>

      {saveError && (
        <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
          {saveError}
        </div>
      )}

      <Button onClick={onSave} disabled={!(probed || preview) || saving} className="w-full">
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        {preview ? "Continue (preview)" : "Save and continue"}
      </Button>
    </div>
  );
}

// ---------- Step: Webhook ----------

function WebhookStep({ preview, onDone }: { preview: boolean; onDone: (configured: boolean) => void }) {
  const [url, setUrl] = useState("");
  const [probe, setProbe] = useState<ProbeState>({ kind: "idle" });
  const [saving, setSaving] = useState(false);

  const onTest = async () => {
    if (!url.trim()) return;
    setProbe({ kind: "probing" });
    try {
      const r = await api.probeWebhook(url.trim());
      if (r.ok) setProbe({ kind: "ok" });
      else setProbe({ kind: "err", message: r.error || "Delivery failed" });
    } catch (e) {
      setProbe({
        kind: "err",
        message: e instanceof Error ? e.message : "Test failed",
      });
    }
  };

  const onSave = async () => {
    setSaving(true);
    if (preview) {
      onDone(true);
      return;
    }
    try {
      await api.updateSettings({ webhook_url: url.trim() });
      onDone(true);
    } catch {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Bell className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-bold tracking-tight">Wire up alerts (optional)</h2>
      </div>
      <p className="text-xs font-medium text-muted-foreground">
        A Slack / Discord / Mattermost incoming webhook URL. Used for failure
        and SLA breach notifications. We&apos;ll send a test message to confirm
        delivery.
      </p>

      <label className="flex flex-col gap-1">
        <FieldLabel>Webhook URL</FieldLabel>
        <input
          type="text"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setProbe({ kind: "idle" });
          }}
          placeholder="https://hooks.slack.com/services/..."
          className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
        />
      </label>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onTest}
          disabled={!url.trim() || probe.kind === "probing"}
        >
          Send test
        </Button>
        <ProbeBadge state={probe} />
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          onClick={() => onDone(false)}
          className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          Skip for now
        </button>
        <Button onClick={onSave} disabled={!url.trim() || saving} size="sm">
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save and continue
        </Button>
      </div>
    </div>
  );
}

// ---------- Step: Gemini ----------

function AIStep({ preview, onDone }: { preview: boolean; onDone: (configured: boolean) => void }) {
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    if (preview) {
      onDone(true);
      return;
    }
    try {
      await api.updateSettings({ gemini_api_key: key.trim() });
      onDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-bold tracking-tight">AI features (optional)</h2>
      </div>
      <p className="text-xs font-medium text-muted-foreground">
        A Google Gemini API key enables failure analysis, stakeholder summaries,
        and report narratives. The free tier (
        <a
          href="https://aistudio.google.com/apikey"
          target="_blank"
          rel="noreferrer"
          className="underline hover:text-foreground"
        >
          aistudio.google.com/apikey
        </a>
        ) is plenty for normal use.
      </p>

      <label className="flex flex-col gap-1">
        <FieldLabel>Gemini API key</FieldLabel>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="AIza..."
          className="h-8 w-full rounded border border-border bg-background px-2 font-mono text-xs"
        />
      </label>

      {error && (
        <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs font-medium text-danger">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          onClick={() => onDone(false)}
          className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          Skip for now
        </button>
        <Button onClick={onSave} disabled={!key.trim() || saving} size="sm">
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save and continue
        </Button>
      </div>
    </div>
  );
}

// ---------- Step: Done ----------

function DoneStep({ summary, onOpen }: { summary: Summary; onOpen: () => void }) {
  return (
    <div className="space-y-4 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success/15 text-success">
        <CheckCircle2 className="h-6 w-6" />
      </div>
      <div className="space-y-2">
        <h2 className="text-base font-bold tracking-tight">You&apos;re all set</h2>
        <p className="text-xs font-medium text-muted-foreground">
          PipelinePulse is now syncing from your Airflow. The first run history
          will appear within a couple of minutes.
        </p>
      </div>

      <ul className="space-y-1.5 text-left text-xs">
        <li className="flex items-center gap-2">
          <Check className="h-3.5 w-3.5 text-success" />
          <span className="font-medium">
            Airflow connected — <span className="font-mono">{summary.airflowName}</span>
          </span>
        </li>
        <li className="flex items-center gap-2">
          {summary.webhookConfigured ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <span className="inline-block h-3.5 w-3.5 rounded-full border border-border" />
          )}
          <span className={cn("font-medium", !summary.webhookConfigured && "text-muted-foreground")}>
            Webhook alerts {summary.webhookConfigured ? "configured" : "skipped (you can add later in Settings)"}
          </span>
        </li>
        <li className="flex items-center gap-2">
          {summary.aiConfigured ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <span className="inline-block h-3.5 w-3.5 rounded-full border border-border" />
          )}
          <span className={cn("font-medium", !summary.aiConfigured && "text-muted-foreground")}>
            AI features {summary.aiConfigured ? "enabled" : "skipped (you can add later in Settings)"}
          </span>
        </li>
      </ul>

      <Button onClick={onOpen} className="w-full">
        Open dashboard
        <ArrowRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
