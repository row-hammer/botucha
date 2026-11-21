"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StepPanel } from "@/components/step-panel";
import { OutcomeBadge, useTriggerLabel } from "@/components/trace-bits";
import { TraceGraph } from "@/components/trace-graph";
import { TraceTable } from "@/components/trace-table";
import { TraceWaterfall } from "@/components/trace-waterfall";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { fmtMs, fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { onTrace } from "@/lib/live";
import type { Step, TraceDetail, TraceSummary } from "@/lib/types";

const PAGE = 50;

function TraceList() {
  const t = useT();
  const [kind, setKind] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [rows, setRows] = useState<TraceSummary[] | null>(null);
  const [more, setMore] = useState(false);

  const query = useCallback(
    (before?: number) => {
      const p = new URLSearchParams({ limit: String(PAGE) });
      if (kind !== "all") p.set("kind", kind);
      if (outcome !== "all") p.set("outcome", outcome);
      if (before) p.set("before_id", String(before));
      return api<TraceSummary[]>(`/api/traces?${p}`);
    },
    [kind, outcome],
  );
  useEffect(() => {
    query()
      .then((r) => {
        setRows(r);
        setMore(r.length === PAGE);
      })
      .catch(() => setRows([]));
  }, [query]);
  useEffect(
    () =>
      onTrace((tr) => {
        if ((kind === "all" || tr.kind === kind) && (outcome === "all" || tr.outcome === outcome))
          setRows((cur) =>
            cur ? (cur.some((r) => r.id === tr.id) ? cur.map((r) => (r.id === tr.id ? tr : r)) : [tr, ...cur]) : cur,
          );
      }),
    [kind, outcome],
  );
  const older = () => {
    if (!rows?.length) return;
    query(rows[rows.length - 1].id).then((r) => {
      setRows([...rows, ...r]);
      setMore(r.length === PAGE);
    });
  };

  return (
    <>
      <PageHeader title={t("nav.thinking")}>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger size="sm" className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["all", "reply", "learn", "describe"].map((k) => (
              <SelectItem key={k} value={k}>
                {t(`thinking.kind.${k}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={outcome} onValueChange={setOutcome}>
          <SelectTrigger size="sm" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["all", "sent", "fallback", "canned", "skipped", "error"].map((o) => (
              <SelectItem key={o} value={o}>
                {t(`thinking.outcome.${o}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </PageHeader>
      <div className="flex flex-col gap-3 p-4">
        {rows === null ? (
          <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
        ) : rows.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground text-sm">{t("thinking.empty")}</CardContent>
          </Card>
        ) : (
          <TraceTable rows={rows} />
        )}
        {more ? (
          <Button variant="outline" className="self-center" onClick={older}>
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
  const [data, setData] = useState<TraceDetail | null | undefined>(undefined);
  const [selected, setSelected] = useState<Step | null>(null);
  useEffect(() => {
    api<TraceDetail>(`/api/traces/${id}`)
      .then(setData)
      .catch(() => setData(null));
  }, [id]);
  const back = (
    <Button asChild size="sm" variant="ghost">
      <Link href="/thinking/">
        <ArrowLeft />
        {t("thinking.back")}
      </Link>
    </Button>
  );
  if (data === undefined) return <PageHeader title={t("nav.thinking")}>{back}</PageHeader>;
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
