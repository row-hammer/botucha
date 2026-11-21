"use client";

import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { OutcomeBadge, useTriggerLabel } from "@/components/trace-bits";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fmtMs, fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import type { TraceSummary } from "@/lib/types";

export function TraceTable({ rows }: { rows: TraceSummary[] }) {
  const t = useT();
  const locale = useLocale();
  const trig = useTriggerLabel();
  const router = useRouter();
  const columns = useMemo<ColumnDef<TraceSummary>[]>(
    () => [
      { id: "time", header: t("thinking.cols.time"), cell: ({ row }) => fmtTime(row.original.started, locale) },
      {
        id: "who",
        header: t("thinking.cols.who"),
        cell: ({ row }) => (row.original.kind === "learn" ? t("thinking.kind.learn") : (row.original.user_name ?? "–")),
      },
      { id: "trigger", header: t("thinking.cols.trigger"), cell: ({ row }) => trig(row.original.trigger) },
      {
        id: "reply",
        header: t("thinking.cols.reply"),
        cell: ({ row }) => (
          <span className="line-clamp-1 max-w-[28rem] text-muted-foreground">
            {row.original.reply ?? row.original.error ?? ""}
          </span>
        ),
      },
      {
        id: "duration",
        header: t("thinking.cols.duration"),
        cell: ({ row }) => <span className="tabular-nums">{fmtMs(row.original.duration_ms)}</span>,
      },
      { id: "attempts", header: t("thinking.cols.attempts"), cell: ({ row }) => row.original.attempts || "–" },
      {
        id: "outcome",
        header: t("thinking.cols.outcome"),
        cell: ({ row }) => <OutcomeBadge outcome={row.original.outcome} />,
      },
    ],
    [t, locale, trig],
  );
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => String(r.id),
  });
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((g) => (
            <TableRow key={g.id}>
              {g.headers.map((h) => (
                <TableHead key={h.id}>{flexRender(h.column.columnDef.header, h.getContext())}</TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer"
              onClick={() => router.push(`/thinking/?id=${row.original.id}`)}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
