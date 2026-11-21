"use client";

import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Confirm } from "@/components/confirm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api, post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Fact, PeopleGraph, Person } from "@/lib/types";

export function PersonPanel({
  person,
  graph,
  onClose,
  onChanged,
}: {
  person: Person | null;
  graph: PeopleGraph;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useT();
  const [facts, setFacts] = useState<Fact[]>([]);
  const [aliases, setAliases] = useState("");
  useEffect(() => {
    if (!person) return;
    setAliases(person.aliases.join(", "));
    api<Fact[]>(`/api/facts?kind=fact&person_id=${person.id}`)
      .then(setFacts)
      .catch(() => setFacts([]));
  }, [person]);
  const names = new Map(graph.people.map((p) => [p.id, p.name]));
  const rels = person ? graph.relations.filter((r) => r.a === person.id || r.b === person.id) : [];

  const saveAliases = async () => {
    if (!person) return;
    try {
      await post(`/api/people/${person.id}`, { aliases: aliases.split(",") }, "PUT");
      toast.success(t("common.saved"));
      onChanged();
    } catch {
      /* api() already showed the error */
    }
  };
  const deleteRel = async (id: number) => {
    try {
      await api(`/api/relations/${id}`, { method: "DELETE" });
      toast.success(t("common.deleted"));
    } catch {
      /* api() already showed the error */
    }
    onChanged();
  };

  return (
    <Sheet open={person !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        {person ? (
          <>
            <SheetHeader>
              <SheetTitle>{person.name}</SheetTitle>
              <SheetDescription>{person.user_id ? t("people.member") : t("people.friend")}</SheetDescription>
            </SheetHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-6 px-4 pb-6">
                <section className="flex flex-col gap-2">
                  <Label htmlFor="aliases">{t("people.aliases")}</Label>
                  <Input id="aliases" value={aliases} onChange={(e) => setAliases(e.target.value)} />
                  <p className="text-muted-foreground text-xs">{t("people.aliasesHint")}</p>
                  <Button size="sm" variant="outline" className="self-start" onClick={saveAliases}>
                    {t("people.saveAliases")}
                  </Button>
                </section>
                <section className="flex flex-col gap-2">
                  <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
                    {t("people.relations")}
                  </h3>
                  {rels.length ? (
                    <ul className="flex flex-col gap-1">
                      {rels.map((r) => (
                        <li key={r.id} className="flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
                          <span>
                            {names.get(r.a)} – <span className="font-medium">{r.rel}</span> → {names.get(r.b)}
                          </span>
                          <Confirm
                            text={`${names.get(r.a)} – ${r.rel} → ${names.get(r.b)}`}
                            onConfirm={() => deleteRel(r.id)}
                          >
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              className="ml-auto"
                              aria-label={t("people.deleteRelation")}
                            >
                              <Trash2 />
                            </Button>
                          </Confirm>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground text-sm">{t("people.noRelations")}</p>
                  )}
                </section>
                <section className="flex flex-col gap-2">
                  <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
                    {t("people.facts")}
                  </h3>
                  {facts.length ? (
                    <ul className="flex flex-col gap-1.5">
                      {facts.map((f) => (
                        <li key={f.id} className="rounded-md border p-2 text-sm">
                          <span className="mr-2 text-muted-foreground text-xs">#{f.id}</span>
                          {f.text}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground text-sm">{t("people.noFacts")}</p>
                  )}
                </section>
              </div>
            </ScrollArea>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
