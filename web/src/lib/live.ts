"use client";

import { create } from "zustand";
import { invalidateTraceData } from "@/lib/query";
import type { Progress, Status, TraceSummary } from "@/lib/types";

type Listener = (t: TraceSummary) => void;
const listeners = new Set<Listener>();
let source: EventSource | null = null;

export const useLive = create<{ status: Status | null; connected: boolean; running: Record<number, Progress> }>(() => ({
  status: null,
  connected: false,
  running: {},
}));

/** One shared EventSource for the whole app; reconnects on its own (EventSource retries). */
export function startLive(): void {
  if (source || typeof window === "undefined") return;
  source = new EventSource("/api/live");
  source.addEventListener("open", () => useLive.setState({ connected: true }));
  source.addEventListener("error", () => useLive.setState({ connected: false, running: {} }));
  source.addEventListener("status", (e) => useLive.setState({ status: JSON.parse((e as MessageEvent).data) }));
  source.addEventListener("progress", onProgress);
  source.addEventListener("trace", (e) => {
    const t = JSON.parse((e as MessageEvent).data) as TraceSummary;
    useLive.setState((s) => {
      const { [t.id]: _done, ...running } = s.running;
      return { running };
    });
    invalidateTraceData(); // every chart and list built from traces refreshes once
    for (const l of listeners) l(t);
  });
}

// a run in progress: which step it finished last (cleared when its trace event arrives)
function onProgress(e: Event) {
  const p = JSON.parse((e as MessageEvent).data) as Progress;
  useLive.setState((s) => ({ running: { ...s.running, [p.id]: p } }));
}

export function onTrace(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
