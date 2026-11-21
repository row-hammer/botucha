"use client";

import { create } from "zustand";
import type { Status, TraceSummary } from "@/lib/types";

type Listener = (t: TraceSummary) => void;
const listeners = new Set<Listener>();
let source: EventSource | null = null;

export const useLive = create<{ status: Status | null; connected: boolean }>(() => ({
  status: null,
  connected: false,
}));

/** One shared EventSource for the whole app; reconnects on its own (EventSource retries). */
export function startLive(): void {
  if (source || typeof window === "undefined") return;
  source = new EventSource("/api/live");
  source.addEventListener("open", () => useLive.setState({ connected: true }));
  source.addEventListener("error", () => useLive.setState({ connected: false }));
  source.addEventListener("status", (e) => useLive.setState({ status: JSON.parse((e as MessageEvent).data) }));
  source.addEventListener("trace", (e) => {
    const t = JSON.parse((e as MessageEvent).data) as TraceSummary;
    for (const l of listeners) l(t);
  });
}

export function onTrace(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
