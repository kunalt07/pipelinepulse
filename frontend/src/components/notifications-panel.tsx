"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, CheckCircle2, Loader2, Send, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";

type Notif = {
  id: number;
  dag_id: string;
  run_id: string;
  event: string;
  delivered: string;
  created_at: string | null;
};

export function NotificationsPanel() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [items, setItems] = useState<Notif[]>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await api.notifications();
      setConfigured(r.configured);
      setItems(r.notifications);
    } catch {
      setConfigured(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const fireTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testNotification();
      setTestResult(r.delivered);
      await load();
    } catch (e) {
      setTestResult(e instanceof Error ? e.message : "Failed");
    } finally {
      setTesting(false);
    }
  };

  const recentDelivered = items.filter((n) => n.delivered === "ok").slice(0, 5);
  const recentFailed = items.filter((n) => n.delivered.startsWith("error"));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          {configured ? (
            <>
              <Bell className="h-3.5 w-3.5 text-success" />
              <span className="text-muted-foreground">Webhook configured</span>
            </>
          ) : (
            <>
              <BellOff className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">No webhook set</span>
            </>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fireTest}
          disabled={!configured || testing}
        >
          {testing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
          Test alert
        </Button>
      </div>

      {!configured && (
        <p className="rounded-md border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground">
          Set <code className="font-mono text-foreground">WEBHOOK_URL</code> in your{" "}
          <code className="font-mono text-foreground">.env</code> (Slack, Discord, Mattermost,
          Google Chat, or any URL accepting <code className="font-mono">{`{"text": "..."}`}</code>{" "}
          JSON), then restart the backend.
        </p>
      )}

      {testResult && (
        <p
          className={cn(
            "text-xs",
            testResult === "ok" ? "text-success" : "text-danger",
          )}
        >
          Test: {testResult}
        </p>
      )}

      {items.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Recent alerts
          </div>
          <ul className="divide-y rounded-md border">
            {items.slice(0, 6).map((n) => (
              <li key={n.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                {n.delivered === "ok" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
                ) : n.delivered === "skipped" ? (
                  <BellOff className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                ) : (
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-danger" />
                )}
                <div className="flex-1 truncate">
                  <span className="font-mono">{n.dag_id}</span>{" "}
                  <span className="text-muted-foreground">— {n.event}</span>
                </div>
                <span className="text-muted-foreground">
                  {formatRelativeTime(n.created_at)}
                </span>
              </li>
            ))}
          </ul>
          {recentFailed.length > 0 && (
            <p className="text-[11px] text-danger">
              {recentFailed.length} delivery error{recentFailed.length === 1 ? "" : "s"} —
              check backend logs
            </p>
          )}
          <p className="text-[10px] text-muted-foreground">
            {recentDelivered.length} delivered · {items.length} total
          </p>
        </div>
      )}
    </div>
  );
}
