"use client";

import { useEffect, useState } from "react";
import { statusText } from "@/components/trace-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { fmtMs } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Step } from "@/lib/types";
import { cn } from "@/lib/utils";

type Hit = { id?: number; first_msg_id?: number; preview: string; score: number; fts: boolean };
type Check = { name: string; ok: boolean; reason?: string };
type Rejected = { text: string; reason: string };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">{title}</h3>
      {children}
    </section>
  );
}

function Hits({ hits, t }: { hits: Hit[]; t: ReturnType<typeof useT> }) {
  if (!hits.length) return <p className="text-muted-foreground text-sm">–</p>;
  return (
    <ul className="flex flex-col gap-1.5">
      {hits.map((h) => (
        <li key={`${h.id ?? h.first_msg_id}`} className="rounded-md border p-2 text-sm">
          <div className="mb-1 flex items-center gap-2 text-xs">
            <span className="font-mono tabular-nums">{h.score.toFixed(3)}</span>
            <div className="h-1.5 w-20 overflow-hidden bg-muted">
              <div className="h-full bg-chart-2" style={{ width: `${Math.max(0, Math.min(1, h.score)) * 100}%` }} />
            </div>
            {h.fts ? <Badge variant="secondary">{t("thinking.panel.fts")}</Badge> : null}
            {h.id ? <span className="ml-auto text-muted-foreground">#{h.id}</span> : null}
          </div>
          <p className="whitespace-pre-wrap break-words">{h.preview}</p>
        </li>
      ))}
    </ul>
  );
}

function KeyValues({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="break-words font-mono">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function PromptView({ traceId, t }: { traceId: number; t: ReturnType<typeof useT> }) {
  const [prompt, setPrompt] = useState<string | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (open && prompt === undefined)
      api<{ prompt: string | null }>(`/api/traces/${traceId}/prompt`)
        .then((r) => setPrompt(r.prompt))
        .catch(() => setPrompt(null));
  }, [open, prompt, traceId]);
  return (
    <div className="flex flex-col gap-2">
      <Button size="sm" variant="outline" className="self-start" onClick={() => setOpen((o) => !o)}>
        {open ? t("thinking.panel.hidePrompt") : t("thinking.panel.showPrompt")}
      </Button>
      {open ? (
        prompt ? (
          <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs">
            {prompt}
          </pre>
        ) : (
          <p className="text-muted-foreground text-sm">
            {prompt === null ? t("thinking.panel.promptGone") : t("common.loading")}
          </p>
        )
      ) : null}
    </div>
  );
}

function Body({ step, traceId }: { step: Step; traceId: number }) {
  const t = useT();
  const d = step.detail as Record<string, unknown>;
  const err =
    typeof d.error === "string" ? (
      <Section title={t("thinking.panel.error")}>
        <p className="text-sm text-warn">{d.error}</p>
      </Section>
    ) : null;
  switch (step.kind) {
    case "context":
      return (
        <KeyValues
          rows={[
            [t("thinking.panel.history"), String(d.history ?? "–")],
            [t("thinking.panel.ownDropped"), String(d.own_dropped ?? "–")],
          ]}
        />
      );
    case "retrieval":
      return (
        <>
          {d.query ? (
            <Section title={t("thinking.panel.query")}>
              <p className="whitespace-pre-wrap rounded-md bg-muted p-2 text-sm">{String(d.query)}</p>
            </Section>
          ) : null}
          <Section title={t("thinking.panel.facts")}>
            <Hits hits={(d.facts as Hit[]) ?? []} t={t} />
          </Section>
          <Section title={t("thinking.panel.chunks")}>
            <Hits hits={(d.chunks as Hit[]) ?? []} t={t} />
          </Section>
          {(d.prices as string[] | undefined)?.length ? (
            <Section title={t("thinking.panel.prices")}>
              <ul className="font-mono text-sm">
                {(d.prices as string[]).map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Section>
          ) : null}
        </>
      );
    case "prompt": {
      const sections = Object.entries(d).filter(([k, v]) => typeof v === "number" && k !== "approx_tokens") as [
        string,
        number,
      ][];
      const max = Math.max(...sections.map(([, v]) => v), 1);
      return (
        <>
          <Section
            title={`${t("thinking.panel.sections")} · ${t("thinking.panel.tokens", { n: Number(d.approx_tokens ?? 0) })}`}
          >
            <ul className="flex flex-col gap-1">
              {sections.map(([k, v]) => (
                <li key={k} className="grid grid-cols-[8rem_1fr_5rem] items-center gap-2 text-xs">
                  <span>{t(`sections.${k}`)}</span>
                  <span className="h-2 rounded-none bg-muted">
                    <span className="block h-2 rounded-none bg-chart-1" style={{ width: `${(v / max) * 100}%` }} />
                  </span>
                  <span className="text-right tabular-nums text-muted-foreground">
                    {t("thinking.panel.chars", { n: v })}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
          <PromptView traceId={traceId} t={t} />
        </>
      );
    }
    case "generation": {
      const keys = [
        "model",
        "prompt_eval_count",
        "eval_count",
        "tok_s",
        "eval_ms",
        "prompt_eval_ms",
        "load_ms",
        "total_ms",
      ];
      const rows = keys
        .filter((k) => d[k] != null)
        .map((k): [string, string] => {
          const v = d[k];
          const shown = k.endsWith("_ms") ? fmtMs(Number(v)) : k === "tok_s" ? Number(v).toFixed(1) : String(v);
          return [t(`thinking.stats.${k}`), shown];
        });
      return (
        <>
          {err}
          {rows.length ? (
            <Section title={t("thinking.panel.stats")}>
              <KeyValues rows={rows} />
            </Section>
          ) : null}
          {typeof d.raw === "string" ? (
            <Section title={t("thinking.panel.raw")}>
              <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs">{d.raw}</pre>
            </Section>
          ) : null}
        </>
      );
    }
    case "filter":
      return (
        <Section title={t("thinking.panel.checks")}>
          <ul className="flex flex-col gap-1.5">
            {((d.checks as Check[]) ?? []).map((c) => (
              <li key={c.name} className="flex items-start gap-2 text-sm">
                <span className={cn("font-mono", c.ok ? "text-ok" : "text-bad")}>{c.ok ? "✓" : "✗"}</span>
                <span className="font-medium">{t(`checks.${c.name}`)}</span>
                {c.reason ? <span className="text-muted-foreground">— {c.reason}</span> : null}
              </li>
            ))}
          </ul>
        </Section>
      );
    case "send":
      return <KeyValues rows={[[t("thinking.panel.msgIds"), ((d.msg_ids as number[]) ?? []).join(", ") || "–"]]} />;
    case "facts":
    case "slang":
    case "extract":
      return (
        <>
          {err}
          {d.added ? (
            <Section title={t("thinking.panel.added")}>
              <ul className="list-disc pl-5 text-sm">
                {((d.added as string[]) ?? []).map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Section>
          ) : null}
          {(d.rejected as Rejected[] | undefined)?.length ? (
            <Section title={t("thinking.panel.rejected")}>
              <ul className="flex flex-col gap-1 text-sm">
                {(d.rejected as Rejected[]).map((r) => (
                  <li key={r.text}>
                    <Badge variant="outline" className="mr-2">
                      {r.reason}
                    </Badge>
                    {r.text}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
          {typeof d.raw === "string" ? (
            <Section title={t("thinking.panel.raw")}>
              <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs">{d.raw}</pre>
            </Section>
          ) : null}
        </>
      );
    default:
      return Object.keys(d).length ? (
        <pre className="whitespace-pre-wrap break-words font-mono text-xs">{JSON.stringify(d, null, 2)}</pre>
      ) : (
        <p className="text-muted-foreground text-sm">{t("thinking.panel.noDetail")}</p>
      );
  }
}

export function StepPanel({ step, traceId, onClose }: { step: Step | null; traceId: number; onClose: () => void }) {
  const t = useT();
  return (
    <Sheet open={step !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-xl">
        {step ? (
          <>
            <SheetHeader>
              <SheetTitle>
                {t(`step.${step.kind}`)}
                {step.name ? <span className="ml-1 text-muted-foreground">#{step.name.replace(/\D/g, "")}</span> : null}
              </SheetTitle>
              <SheetDescription className="flex gap-4">
                <span>
                  {t("thinking.panel.status")}:{" "}
                  <span className={statusText[step.status]}>{t(`stepStatus.${step.status}`)}</span>
                </span>
                <span>
                  {t("thinking.panel.duration")}: {fmtMs(step.duration_ms)}
                </span>
              </SheetDescription>
            </SheetHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-5 px-4 pb-6">
                <Body step={step} traceId={traceId} />
              </div>
            </ScrollArea>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
