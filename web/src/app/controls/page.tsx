"use client";

import { Play, RefreshCw, RotateCw, Square } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Confirm } from "@/components/confirm";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { post } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { useLive } from "@/lib/live";
import { useApi } from "@/lib/query";
import type { Status } from "@/lib/types";

export default function ControlsPage() {
  const t = useT();
  const locale = useLocale();
  const live = useLive((s) => s.status);
  const first = useApi<Status>("/api/status");
  const journal = useApi<{ lines: string[] }>("/api/control/journal?n=50");
  const [status, setStatus] = useState<Status | null>(null);
  const [freq, setFreq] = useState("");
  const [custom, setCustom] = useState("");
  const lines = journal.data?.lines ?? [];
  const s = status ?? live ?? first.data ?? null;

  useEffect(() => {
    if (first.data) setFreq((cur) => cur || String(first.data.random_n)); // fill the field once
  }, [first.data]);
  useEffect(() => {
    if (live) setStatus(live);
  }, [live]);
  const loadJournal = useCallback(() => void journal.refetch(), [journal]);

  const apply = async (body: Record<string, unknown>) => {
    try {
      setStatus(await post<Status>("/api/control/state", body));
      toast.success(t("controls.applied"));
    } catch {
      /* api() already showed the error */
    }
  };
  const service = async (action: "start" | "stop" | "restart") => {
    try {
      await post("/api/control/service", { action });
      toast.success(t("controls.done"));
    } catch {
      /* api() already showed the error (e.g. systemctl output) */
    }
    setTimeout(loadJournal, 3000);
  };
  const quiet = s && s.quiet_until * 1000 > Date.now();

  return (
    <>
      <PageHeader title={t("nav.controls")} />
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        {first.error && !s ? (
          <div className="lg:col-span-2">
            <QueryError error={first.error} onRetry={() => first.refetch()} />
          </div>
        ) : null}
        <Card>
          <CardHeader>
            <CardTitle>{t("controls.replying")}</CardTitle>
            <CardDescription>{t("controls.replyingHint")}</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-3">
            <Switch
              checked={s?.enabled ?? false}
              onCheckedChange={(v) => apply({ enabled: v })}
              aria-label={t("controls.replying")}
            />
            <span className="text-sm">{s?.enabled ? t("status.enabled") : t("status.disabled")}</span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("controls.frequency")}</CardTitle>
            <CardDescription>{t("controls.frequencyHint")}</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-2">
            <span className="text-sm">1 /</span>
            <Input className="w-24" type="number" min={2} value={freq} onChange={(e) => setFreq(e.target.value)} />
            <Button size="sm" disabled={!(Number(freq) >= 2)} onClick={() => apply({ random_n: Number(freq) })}>
              {t("common.save")}
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("controls.quiet")}</CardTitle>
            <CardDescription>
              {t("controls.quietHint")}
              {quiet && s ? (
                <span className="mt-1 block font-medium text-warn">
                  {t("status.quietUntil", { time: fmtTime(s.quiet_until, locale, false) })}
                </span>
              ) : null}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            {[15, 60, 180].map((m) => (
              <Button key={m} size="sm" variant="outline" onClick={() => apply({ quiet_min: m })}>
                {t("controls.quietFor", { n: m })}
              </Button>
            ))}
            <Input
              className="w-28"
              type="number"
              min={1}
              placeholder={t("controls.quietCustom")}
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!(Number(custom) > 0)}
              onClick={() => apply({ quiet_min: Number(custom) })}
            >
              {t("common.save")}
            </Button>
            {quiet ? (
              <Button size="sm" variant="ghost" onClick={() => apply({ quiet_min: 0 })}>
                {t("controls.quietOff")}
              </Button>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {t("controls.service")} <StatusBadge state={s?.bot} />
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => service("start")} disabled={s?.bot === "active"}>
              <Play />
              {t("controls.start")}
            </Button>
            <Confirm
              text={t("controls.restartConfirm")}
              action={t("controls.restart")}
              onConfirm={() => service("restart")}
            >
              <Button size="sm" variant="outline">
                <RotateCw />
                {t("controls.restart")}
              </Button>
            </Confirm>
            <Confirm text={t("controls.stopConfirm")} action={t("controls.stop")} onConfirm={() => service("stop")}>
              <Button size="sm" variant="outline" className="text-bad" disabled={s?.bot !== "active"}>
                <Square />
                {t("controls.stop")}
              </Button>
            </Confirm>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t("controls.journal")}</CardTitle>
            <Button size="sm" variant="ghost" onClick={loadJournal}>
              <RefreshCw />
              {t("common.refresh")}
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs">
              {lines.join("\n") || "–"}
            </pre>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
