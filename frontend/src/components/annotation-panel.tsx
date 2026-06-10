"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, StickyNote } from "lucide-react";
import { api } from "@/lib/api";

type Props = {
  dagId: string;
  runId: string;
  onChange?: (hasNote: boolean) => void;
};

type SaveState = "idle" | "saving" | "saved" | "error";

export function AnnotationPanel({ dagId, runId, onChange }: Props) {
  const [note, setNote] = useState("");
  const [original, setOriginal] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>("idle");
  const [loading, setLoading] = useState(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSave("idle");
    api
      .getAnnotation(dagId, runId)
      .then((a) => {
        if (cancelled) return;
        setNote(a.note);
        setOriginal(a.note);
        setUpdatedAt(a.updated_at);
        onChange?.(!!a.note);
      })
      .catch(() => {
        if (cancelled) return;
        setNote("");
        setOriginal("");
        setUpdatedAt(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [dagId, runId, onChange]);

  const persist = (next: string) => {
    setNote(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (next === original) {
        setSave("idle");
        return;
      }
      setSave("saving");
      try {
        const saved = await api.upsertAnnotation(dagId, runId, next);
        setOriginal(saved.note);
        setUpdatedAt(saved.updated_at);
        setSave("saved");
        onChange?.(!!saved.note);
        setTimeout(() => setSave("idle"), 1500);
      } catch {
        setSave("error");
        setTimeout(() => setSave("idle"), 3000);
      }
    }, 600);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
          <StickyNote className="h-3 w-3" />
          Note
        </div>
        <div className="flex items-center gap-2">
          {updatedAt && save === "idle" && (
            <span className="text-[10px] font-medium text-muted-foreground">
              saved {updatedAt.split(".")[0]}
            </span>
          )}
          {save === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          {save === "saved" && <Check className="h-3.5 w-3.5 text-success" />}
          {save === "error" && <span className="text-[10px] font-semibold text-danger">save failed</span>}
        </div>
      </div>
      <textarea
        value={note}
        onChange={(e) => persist(e.target.value)}
        disabled={loading}
        placeholder="Pin context for this run — known issues, JIRA links, repro steps…"
        rows={3}
        className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs leading-relaxed placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
      />
    </div>
  );
}
