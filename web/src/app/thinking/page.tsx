"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { ArrowLeft, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { useNodeLabel } from "@/components/pipeline-flow";
import { QueryError } from "@/components/query-error";
import { StepPanel } from "@/components/step-panel";
import { OutcomeBadge, useTriggerLabel } from "@/components/trace-bits";
import { TraceGraph } from "@/components/trace-graph";
import { TraceTable } from "@/components/trace-table";
import { TraceWaterfall } from "@/components/trace-waterfall";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { type ApiError, api } from "@/lib/api";
import { fmtMs, fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { useApi } from "@/lib/query";
import type { Step, TraceDetail, TraceSummary } from "@/lib/types";
import { useUrlState } from "@/lib/url-state";

const PAGE = 50;

const KINDS = ["all", "reply", "learn", "describe"] as const;
const OUTCOMES = ["all", "sent", "fallback", "canned", "skipped", "error"] as const;

function TraceList() {
  const t = useT();
  const nodeLabel = useNodeLabel();
  const params = useSearchParams();
  const path = params.get("path"); // drill-down from the Pipeline page
  const range = params.get("range") ?? "30d";
  const [kind, setKind] = useUrlState("kind", "all", KINDS);
  const [outcome, setOutcome] = useUrlState("outcome", "all", OUTCOMES);

  const filters = new URLSearchParams({ limit: String(PAGE) });
  if (path) {
    filters.set("path", path);
    filters.set("range", range);
  } else {
    if (kind !== "all") filters.set("kind", kind);
    if (outcome !== "all") filters.set("outcome", outcome);
  }
  // a finished trace refreshes every loaded page (invalidateTraceData), so new runs appear at the top
  const query = useInfiniteQuery<TraceSummary[], ApiError>({
    queryKey: [`/api/traces?${filters}`],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => {
      const p = new URLSearchParams(filters);
      if (pageParam) p.set("before_id", String(pageParam));
      return api<TraceSummary[]>(`/api/traces?${p}`, { signal }, { quiet: true });
    },
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].id : undefined),
    placeholderData: keepPreviousData,
  });
  const rows = query.data ? query.data.pages.flat() : null;

  return (
    <>
      <PageHeader title={t("nav.thinking")}>
        {path ? (
          <Badge variant="outline" className="gap-1 py-1 pr-1 pl-2.5 text-sm">
            {t("thinking.pathFilter", { node: nodeLabel(path), range: t(`overview.range.${range}`) })}
            <Link
              href="/thinking/"
              aria-label={t("thinking.clearFilter")}
              className="rounded-none p-0.5 hover:bg-muted"
            >
              <X className="size-3.5" />
            </Link>
          </Badge>
        ) : null}
        <Select value={kind} onValueChange={(v) => setKind(v as (typeof KINDS)[number])} disabled={!!path}>
          <SelectTrigger size="sm" className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((k) => (
              <SelectItem key={k} value={k}>
                {t(`thinking.kind.${k}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={outcome} onValueChange={(v) => setOutcome(v as (typeof OUTCOMES)[number])} disabled={!!path}>
          <SelectTrigger size="sm" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OUTCOMES.map((o) => (
              <SelectItem key={o} value={o}>
                {t(`thinking.outcome.${o}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </PageHeader>
      <div className="flex flex-col gap-3 p-4">
        <QueryError error={query.error} onRetry={() => query.refetch()} />
        {rows === null ? (
          query.error ? null : (
            <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
          )
        ) : rows.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground text-sm">{t("thinking.empty")}</CardContent>
          </Card>
        ) : (
          <TraceTable rows={rows} />
        )}
        {query.hasNextPage ? (
          <Button
            variant="outline"
            className="self-center"
            disabled={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            {t("common.loadOlder")}
          </Button>
        ) : null}
      </div>
    </>
  );
}

function TraceView({ id }: { id: number }) {
  const t = useT();
  const locale = useLocale();
  const trig = useTriggerLabel();
  const query = useApi<TraceDetail>(`/api/traces/${id}`);
  // null = gone (older than the 30 days traces are kept); undefined = still loading or failed
  const data = query.error?.status === 404 ? null : query.data;
  const [selected, setSelected] = useState<Step | null>(null);
  const back = (
    <Button asChild size="sm" variant="ghost">
      <Link href="/thinking/">
        <ArrowLeft />
        {t("thinking.back")}
      </Link>
    </Button>
  );
  if (data === undefined)
    return (
      <>
        <PageHeader title={t("nav.thinking")}>{back}</PageHeader>
        <div className="p-4">
          <QueryError error={query.error} onRetry={() => query.refetch()} />
        </div>
      </>
    );
  if (data === null)
    return (
      <>
        <PageHeader title={t("nav.thinking")}>{back}</PageHeader>
        <p className="p-4 text-muted-foreground text-sm">{t("thinking.notFound")}</p>
      </>
    );
  const { trace, steps } = data;
  return (
    <>
      <PageHeader title={`${t("nav.thinking")} #${trace.id}`}>{back}</PageHeader>
      <div className="flex flex-col gap-4 p-4">
        <Card className="py-3">
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 text-sm">
            <OutcomeBadge outcome={trace.outcome} />
            <span>{fmtTime(trace.started, locale)}</span>
            <span>
              <span className="text-muted-foreground">{t("thinking.cols.who")}: </span>
              {trace.kind === "learn" ? t("thinking.kind.learn") : (trace.user_name ?? "–")}
            </span>
            <span>
              <span className="text-muted-foreground">{t("thinking.cols.trigger")}: </span>
              {trig(trace.trigger)}
            </span>
            <span>
              <span className="text-muted-foreground">{t("thinking.cols.duration")}: </span>
              {fmtMs(trace.duration_ms)}
            </span>
          </CardContent>
          {trace.reply || trace.error ? (
            <CardContent className="px-4">
              <p className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{trace.reply ?? trace.error}</p>
            </CardContent>
          ) : null}
        </Card>
        <section className="flex flex-col gap-2">
          <h2 className="font-medium text-sm">{t("thinking.graph")}</h2>
          <TraceGraph
            steps={steps}
            totalMs={trace.duration_ms ?? 0}
            selected={selected?.id ?? null}
            onSelect={setSelected}
          />
        </section>
        <section className="flex flex-col gap-2">
          <h2 className="font-medium text-sm">{t("thinking.timeline")}</h2>
          <TraceWaterfall trace={trace} steps={steps} selected={selected?.id ?? null} onSelect={setSelected} />
        </section>
      </div>
      <StepPanel step={selected} traceId={trace.id} onClose={() => setSelected(null)} />
    </>
  );
}

function Thinking() {
  const id = Number(useSearchParams().get("id"));
  return id ? <TraceView key={id} id={id} /> : <TraceList />;
}

export default function ThinkingPage() {
  return (
    <Suspense>
      <Thinking />
    </Suspense>
  );
}
