"use client";

import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { Confirm } from "@/components/confirm";
import { FactDialog } from "@/components/fact-dialog";
import { PageHeader } from "@/components/page-header";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { invalidate, useApi } from "@/lib/query";
import type { Fact, PeopleGraph } from "@/lib/types";

type Kind = "fact" | "slang";

function sourceKey(s: string): "auto" | "member" | "web" {
  return s.startsWith("cmd:") ? "member" : s === "web" ? "web" : "auto";
}

export default function MemoryPage() {
  const t = useT();
  const locale = useLocale();
  const [kind, setKind] = useState<Kind>("fact");
  const [q, setQ] = useState("");
  const [person, setPerson] = useState("all");
  const [source, setSource] = useState("all");
  const [editing, setEditing] = useState<Fact | null | undefined>(undefined);
  const params = new URLSearchParams({ kind });
  if (person !== "all") params.set("person_id", person);
  if (source !== "all") params.set("source", source);
  const facts = useApi<Fact[]>(`/api/facts?${params}`, { keepPrevious: true });
  const graph = useApi<PeopleGraph>("/api/people").data ?? null;
  const rows = useMemo(() => facts.data ?? [], [facts.data]);
  const load = useCallback(() => invalidate("/api/facts", "/api/people"), []);

  const names = useMemo(() => new Map(graph?.people.map((p) => [p.id, p.name]) ?? []), [graph]);
  const shown = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase();
    return needle ? rows.filter((r) => r.text.toLocaleLowerCase().includes(needle)) : rows;
  }, [rows, q]);

  const remove = useCallback(
    async (f: Fact) => {
      try {
        await api(`/api/facts/${f.id}`, { method: "DELETE" });
        toast.success(t("common.deleted"));
      } catch {
        /* api() already showed the error */
      }
      load();
    },
    [load, t],
  );

  const columns = useMemo<ColumnDef<Fact>[]>(
    () => [
      {
        id: "id",
        header: t("memory.cols.id"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.id}</span>,
      },
      {
        id: "text",
        header: t("memory.cols.text"),
        cell: ({ row }) => <span className="whitespace-normal break-words">{row.original.text}</span>,
      },
      {
        id: "people",
        header: t("memory.cols.people"),
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.people.map((id) => (
              <Badge key={id} variant="secondary">
                {names.get(id) ?? id}
              </Badge>
            ))}
          </div>
        ),
      },
      {
        id: "source",
        header: t("memory.cols.source"),
        cell: ({ row }) => (
          <span className="text-muted-foreground text-xs">{t(`memory.source.${sourceKey(row.original.source)}`)}</span>
        ),
      },
      {
        id: "updated",
        header: t("memory.cols.updated"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-muted-foreground text-xs">
            {fmtTime(row.original.updated, locale)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={t("common.edit")}
              onClick={() => setEditing(row.original)}
            >
              <Pencil />
            </Button>
            <Confirm text={t("memory.deleteConfirm", { id: row.original.id })} onConfirm={() => remove(row.original)}>
              <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")}>
                <Trash2 />
              </Button>
            </Confirm>
          </div>
        ),
      },
    ],
    [t, locale, names, remove],
  );
  const table = useReactTable({
    data: shown,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => String(r.id),
  });

  return (
    <>
      <PageHeader title={t("nav.memory")}>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus />
          {t(`memory.add.${kind}`)}
        </Button>
      </PageHeader>
      <div className="flex flex-col gap-3 p-4">
        <QueryError error={facts.error} onRetry={() => facts.refetch()} />
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={kind} onValueChange={(v) => setKind(v as Kind)}>
            <TabsList>
              <TabsTrigger value="fact">{t("memory.tabs.fact")}</TabsTrigger>
              <TabsTrigger value="slang">{t("memory.tabs.slang")}</TabsTrigger>
            </TabsList>
          </Tabs>
          <Input
            className="h-8 w-56"
            placeholder={t("common.search")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {kind === "fact" ? (
            <Select value={person} onValueChange={setPerson}>
              <SelectTrigger size="sm" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("memory.anyPerson")}</SelectItem>
                {graph?.people.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger size="sm" className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {["all", "auto", "member", "web"].map((s) => (
                <SelectItem key={s} value={s}>
                  {t(`memory.source.${s}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-auto text-muted-foreground text-xs">{t("memory.count", { n: shown.length })}</span>
        </div>
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
              {table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className={cell.column.id === "text" ? "w-full" : undefined}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length} className="py-8 text-center text-muted-foreground">
                    {t("memory.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
      <FactDialog
        open={editing !== undefined}
        kind={editing?.kind ?? kind}
        fact={editing ?? null}
        onClose={() => setEditing(undefined)}
        onSaved={load}
      />
    </>
  );
}
