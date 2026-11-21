"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/page-header";
import { PeopleGraphView } from "@/components/people-graph";
import { PersonPanel } from "@/components/person-panel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { PeopleGraph, Person } from "@/lib/types";

export default function PeoplePage() {
  const t = useT();
  const [graph, setGraph] = useState<PeopleGraph | null>(null);
  const [selected, setSelected] = useState<Person | null>(null);
  const [link, setLink] = useState<{ a: number; b: number } | null>(null);
  const [rel, setRel] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api<PeopleGraph>("/api/people")
      .then((g) => {
        setGraph(g);
        setSelected((s) => (s ? (g.people.find((p) => p.id === s.id) ?? null) : null));
      })
      .catch(() => {});
  }, []);
  useEffect(load, [load]);
  const nameOf = (id: number) => graph?.people.find((p) => p.id === id)?.name ?? "";

  const saveRelation = async () => {
    if (!link) return;
    try {
      await post("/api/relations", { a: link.a, rel, b: link.b }, "POST", { inline: [422] });
      toast.success(t("common.saved"));
      setLink(null);
      setRel("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  const savePerson = async () => {
    try {
      await post("/api/people", { name, aliases: aliases.split(",") }, "POST", { inline: [422] });
      toast.success(t("common.saved"));
      setAdding(false);
      setName("");
      setAliases("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <>
      <PageHeader title={t("nav.people")}>
        <span className="hidden text-muted-foreground text-xs md:inline">{t("people.connectHint")}</span>
        <Button
          size="sm"
          onClick={() => {
            setError("");
            setAdding(true);
          }}
        >
          <Plus />
          {t("people.add")}
        </Button>
      </PageHeader>
      <div className="flex flex-col gap-2 p-4">
        <div className="flex gap-4 text-muted-foreground text-xs">
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-5 bg-chart-1" /> {t("people.legendRelation")}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-5 border-muted-foreground border-t-2 border-dashed opacity-50" />{" "}
            {t("people.legendComention")}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-3 rounded-none border-2 border-chart-1/60" /> {t("people.member")}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-3 rounded-none border-2 border-chart-5/60" /> {t("people.friend")}
          </span>
        </div>
        {graph ? (
          <PeopleGraphView
            graph={graph}
            selected={selected?.id ?? null}
            onSelect={setSelected}
            onConnect={(a, b) => {
              setError("");
              setLink({ a, b });
            }}
          />
        ) : (
          <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
        )}
      </div>
      {graph ? (
        <PersonPanel person={selected} graph={graph} onClose={() => setSelected(null)} onChanged={load} />
      ) : null}

      <Dialog open={link !== null} onOpenChange={(o) => !o && setLink(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("people.newRelation")}</DialogTitle>
            <DialogDescription>
              {link ? t("people.relationHint", { a: nameOf(link.a), b: nameOf(link.b) }) : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{link ? nameOf(link.a) : ""}</span>
            <span>–</span>
            <Input
              autoFocus
              maxLength={60}
              value={rel}
              onChange={(e) => setRel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveRelation()}
            />
            <span>→</span>
            <span className="font-medium">{link ? nameOf(link.b) : ""}</span>
          </div>
          {error ? <p className="text-bad text-sm">{error}</p> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setLink(null)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={saveRelation} disabled={!rel.trim()}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("people.add")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="pname">{t("people.name")}</Label>
            <Input id="pname" autoFocus maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
            <Label htmlFor="paliases">{t("people.aliases")}</Label>
            <Input id="paliases" value={aliases} onChange={(e) => setAliases(e.target.value)} />
            <p className="text-muted-foreground text-xs">{t("people.aliasesHint")}</p>
          </div>
          {error ? <p className="text-bad text-sm">{error}</p> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdding(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={savePerson} disabled={!name.trim()}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
