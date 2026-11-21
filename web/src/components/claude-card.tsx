"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { QueryError } from "@/components/query-error";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { queryClient, useApi } from "@/lib/query";
import type { ClaudeStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const REASON_KEY: Record<NonNullable<ClaudeStatus["reason"]>, string> = {
  "disabled in config": "disabled",
  "no API key": "noKey",
  "period ended": "ended",
  "switched off": "off",
  "daily limit reached": "limit",
};

/** Claude proofreading: whether it runs now and why not, today's budget, and the on/off switch. */
export function ClaudeCard() {
  const t = useT();
  const query = useApi<ClaudeStatus>("/api/claude");
  const s = query.data ?? null;
  const [busy, setBusy] = useState(false);

  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      queryClient.setQueryData(["/api/claude"], await post<ClaudeStatus>("/api/control/claude", { on }));
    } catch {
      /* post() already showed the error */
    } finally {
      setBusy(false);
    }
  };

  // the switch only matters once config and key are in place
  const canSwitch = !!s && s.enabled && s.key;
  return (
    <Card className="gap-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="size-4 text-claude" />
          {t("quality.claude.title")}
        </CardTitle>
        <CardDescription className="text-xs">{t("quality.claude.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <QueryError error={query.error} onRetry={() => query.refetch()} />
        {!s ? (
          query.error ? null : (
            <p className="text-muted-foreground">{t("common.loading")}</p>
          )
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className={cn("font-medium", s.allowed ? "text-claude" : "text-muted-foreground")}>
                {s.allowed
                  ? t("quality.claude.on")
                  : t(`quality.claude.reason.${s.reason ? REASON_KEY[s.reason] : "off"}`)}
              </span>
              <div className="flex items-center gap-2">
                <Label htmlFor="claude-switch" className="text-muted-foreground text-xs">
                  {t("quality.claude.switch")}
                </Label>
                <Switch id="claude-switch" checked={s.switch} disabled={!canSwitch || busy} onCheckedChange={toggle} />
              </div>
            </div>
            <dl className="grid grid-cols-3 gap-2 border-t pt-3 text-center">
              <div>
                <dd className="font-semibold tabular-nums">
                  {s.calls_today}/{s.daily_limit}
                </dd>
                <dt className="text-muted-foreground text-xs">{t("quality.claude.calls")}</dt>
              </div>
              <div>
                <dd className="font-semibold tabular-nums">{s.until ?? "–"}</dd>
                <dt className="text-muted-foreground text-xs">{t("quality.claude.until")}</dt>
              </div>
              <div>
                <dd className="truncate font-mono font-semibold text-xs leading-6">{s.model}</dd>
                <dt className="text-muted-foreground text-xs">{t("quality.claude.model")}</dt>
              </div>
            </dl>
            {!s.enabled || !s.key ? (
              <p className="text-muted-foreground text-xs">
                {t(s.enabled ? "quality.claude.setupKey" : "quality.claude.setupEnable")}
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
