"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** A string kept in the URL query (?key=value), so reloads, back/forward and shared links keep it.
 * Values outside `allowed` fall back; the fallback itself is left out of the URL. Pages that use it
 * must render inside <Suspense> (Next.js static export requirement for useSearchParams). */
export function useUrlState<T extends string>(key: string, fallback: T, allowed?: readonly T[]): [T, (v: T) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get(key);
  const value = (raw !== null && (!allowed || (allowed as readonly string[]).includes(raw)) ? raw : fallback) as T;
  const set = useCallback(
    (v: T) => {
      const next = new URLSearchParams(params.toString());
      if (v === fallback) next.delete(key);
      else next.set(key, v);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, key, fallback],
  );
  return [value, set];
}
