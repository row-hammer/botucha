"use client";

import { Download, PencilLine, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { post } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { invalidate, queryClient, useApi } from "@/lib/query";
import type { Rating } from "@/lib/types";

const key = (r: Rating) => `${r.kind}:${r.chat_id}:${r.msg_id}:${r.user_id}`;

export default function RatingsPage() {
  const t = useT();
  const locale = useLocale();
  const query = useApi<Rating[]>("/api/ratings");
  const rows = query.data ?? null;
  const [onlyOpen, setOnlyOpen] = useState(false);
  const shown = useMemo(() => (rows ?? []).filter((r) => !onlyOpen || !r.reviewed), [rows, onlyOpen]);

  const toggle = async (r: Rating, reviewed: boolean) => {
    queryClient.setQueryData<Rating[]>(["/api/ratings"], (cur) =>
      cur?.map((x) => (key(x) === key(r) ? { ...x, reviewed } : x)),
    );
    try {
      await post("/api/ratings/review", {
        kind: r.kind,
        chat_id: r.chat_id,
        msg_id: r.msg_id,
        user_id: r.user_id,
        reviewed,
      });
    } catch {
      invalidate("/api/ratings"); // put the real state back
    }
  };

  return (
    <>
      <PageHeader title={t("nav.ratings")}>
        <div className="flex items-center gap-2">
          <Checkbox id="open" checked={onlyOpen} onCheckedChange={(v) => setOnlyOpen(v === true)} />
          <Label htmlFor="open" className="text-sm">
            {t("ratings.onlyOpen")}
          </Label>
        </div>
        <Button asChild size="sm" variant="outline">
          <a href="/api/ratings/export" download>
            <Download />
            {t("ratings.export")}
          </a>
        </Button>
      </PageHeader>
      <div className="flex flex-col gap-3 p-4">
        <QueryError error={query.error} onRetry={() => query.refetch()} />
        {rows !== null && shown.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground text-sm">{t("ratings.empty")}</CardContent>
          </Card>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  {(["date", "who", "kind", "note", "original", "trace", "reviewed"] as const).map((c) => (
                    <TableHead key={c}>{t(`ratings.cols.${c}`)}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((r) => {
                  const kind = r.kind === "correction" ? "correction" : (r.score ?? 0) > 0 ? "good" : "bad";
                  const Icon = kind === "correction" ? PencilLine : kind === "good" ? ThumbsUp : ThumbsDown;
                  const tone = kind === "correction" ? "text-chart-1" : kind === "good" ? "text-ok" : "text-bad";
                  return (
                    <TableRow key={key(r)} className={r.reviewed ? "opacity-60" : undefined}>
                      <TableCell className="whitespace-nowrap text-muted-foreground text-xs">
                        {fmtTime(r.ts, locale)}
                      </TableCell>
                      <TableCell>{r.user_name ?? r.user_id}</TableCell>
                      <TableCell>
                        <span className={`flex items-center gap-1.5 ${tone}`}>
                          <Icon className="size-4" />
                          {t(`ratings.kind.${kind}`)}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-[24rem] whitespace-normal break-words">
                        {r.text ?? r.reason ?? ""}
                      </TableCell>
                      <TableCell className="max-w-[24rem] whitespace-normal break-words text-muted-foreground">
                        {r.original ?? ""}
                      </TableCell>
                      <TableCell>
                        {r.trace_id ? (
                          <Link
                            className="text-chart-1 underline-offset-4 hover:underline"
                            href={`/thinking/?id=${r.trace_id}`}
                          >
                            {t("ratings.openTrace")}
                          </Link>
                        ) : (
                          t("ratings.noTrace")
                        )}
                      </TableCell>
                      <TableCell>
                        <Checkbox
                          checked={r.reviewed}
                          aria-label={t("ratings.cols.reviewed")}
                          onCheckedChange={(v) => toggle(r, v === true)}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </>
  );
}
