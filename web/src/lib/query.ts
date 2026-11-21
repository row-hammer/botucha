"use client";

import { keepPreviousData, QueryClient, useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

/** Reads go through one cache: retried quietly (the bot may be restarting), then shown inline with a
 * retry button. Saves keep using post() with their toasts and invalidate what they changed. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      // a 4xx will not get better by asking again; network errors, 5xx and "busy" might
      retry: (n, e) => n < 2 && !(e instanceof ApiError && e.status >= 400 && e.status < 500),
      retryDelay: (n) => 500 * 2 ** n,
    },
  },
});

/** GET an API path through the cache. `path` null = not yet (e.g. waiting for an id). */
export function useApi<T>(path: string | null, opts: { keepPrevious?: boolean; refetchMs?: number } = {}) {
  return useQuery<T, ApiError>({
    queryKey: [path],
    queryFn: ({ signal }) => api<T>(path as string, { signal }, { quiet: true }),
    enabled: path !== null,
    placeholderData: opts.keepPrevious ? keepPreviousData : undefined,
    refetchInterval: opts.refetchMs,
  });
}

/** API paths whose answers change whenever a trace finishes. */
const TRACE_DEPENDENT = ["/api/metrics", "/api/pipeline", "/api/quality", "/api/claude", "/api/traces", "/api/ratings"];

export function invalidateTraceData() {
  void queryClient.invalidateQueries({
    predicate: (q) => TRACE_DEPENDENT.some((p) => String(q.queryKey[0] ?? "").startsWith(p)),
  });
}

/** Refresh every cached read of these path prefixes (after a save). */
export function invalidate(...prefixes: string[]) {
  void queryClient.invalidateQueries({
    predicate: (q) => prefixes.some((p) => String(q.queryKey[0] ?? "").startsWith(p)),
  });
}
