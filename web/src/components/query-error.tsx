"use client";

import { RotateCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** Inline error for a failed read, with a retry button. Renders nothing when there is no error. */
export function QueryError({ error, onRetry }: { error: ApiError | null | undefined; onRetry: () => void }) {
  const t = useT();
  if (!error) return null;
  const msg =
    error.status === 0
      ? t("errors.network")
      : error.status === 503
        ? t("errors.busy")
        : t("errors.generic", { msg: error.message });
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 border border-bad/40 bg-bad/10 px-3 py-2 text-bad text-sm"
    >
      <TriangleAlert className="size-4 shrink-0" />
      <span className="min-w-0 flex-1">{msg}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>
        <RotateCw />
        {t("common.retry")}
      </Button>
    </div>
  );
}
