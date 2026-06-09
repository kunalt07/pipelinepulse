"use client";

import { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

type Mode = "explain" | "stakeholder";

type Props = {
  mode: Mode;
  dagId: string;
  runId?: string;
  label: string;
};

export function AIPanel({ mode, dagId, runId, label }: Props) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === "explain") {
        if (!runId) return;
        const r = await api.explain(dagId, runId);
        setText(r.insight);
      } else {
        const r = await api.stakeholder(dagId);
        setText(r.summary);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <Button onClick={run} disabled={loading || (mode === "explain" && !runId)} size="sm">
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
        {label}
      </Button>

      {error && <p className="text-xs text-danger">{error}</p>}

      {text && (
        <div className="rounded-md border bg-muted/30 p-4 text-sm leading-relaxed whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}
