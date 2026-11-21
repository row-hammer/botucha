"use client";

import { create } from "zustand";
import { invalidateTraceData } from "@/lib/query";
import type { Progress, Status, TraceSummary } from "@/lib/types";

type Listener = (t: TraceSummary) => void;
const listeners = new Set<Listener>();
let source: EventSource | null = null;
let retryMs = 1_000;
const MAX_RETRY_MS = 30_000;

export const useLive = create<{ status: Status | null; connected: boolean; running: Record<number, Progress> }>(() => ({
  status: null,
  connected: false,
  running: {},
}));

/** One shared EventSource for the whole app. The browser retries a dropped connection by itself, but gives up
 * for good after an error response (e.g. 503 while the service restarts): then a new one is opened, with backoff.
 * While disconnected the last status is dropped, so nothing shows the bot as running when that is unknown. */
export function startLive(): void {
  if (source || typeof window === "undefined") return;
  const es = new EventSource("/api/live");
  source = es;
  es.addEventListener("open", () => {
    retryMs = 1_000;
    useLive.setState({ connected: true });
  });
  es.addEventListener("error", () => {
    useLive.setState({ connected: false, running: {}, status: null });
    if (es.readyState === EventSource.CLOSED) {
      es.close();
      if (source === es) source = null;
      setTimeout(startLive, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    }
  });
  source.addEventListener("status", (e) => useLive.setState({ status: JSON.parse((e as MessageEvent).data) }));
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
