"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Fact } from "@/lib/types";

export const LIMITS = { fact: 300, slang: 150 } as const;

export function FactDialog({
  open,
  kind,
  fact,
  onClose,
  onSaved,
}: {
  open: boolean;
  kind: "fact" | "slang";
  fact: Fact | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const schema = useMemo(
    () =>
      z.object({
        text: z
          .string()
          .trim()
          .min(1, t("memory.errors.empty"))
          .max(LIMITS[kind], t("memory.errors.long", { n: LIMITS[kind] }))
          .refine((v) => kind === "fact" || /^[^=]+=[^=]+/.test(v), t("memory.errors.slang")),
      }),
    [kind, t],
  );
  const form = useForm<{ text: string }>({ resolver: zodResolver(schema), defaultValues: { text: "" } });
  useEffect(() => {
    if (open) form.reset({ text: fact?.text ?? "" });
  }, [open, fact, form]);
  const submit = form.handleSubmit(async ({ text }) => {
    try {
      if (fact) await post(`/api/facts/${fact.id}`, { text }, "PUT");
      else await post("/api/facts", { kind, text });
      toast.success(t("common.saved"));
      onSaved();
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) form.setError("text", { message: e.message });
    }
  });
  const len = form.watch("text").length;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{fact ? `${t("memory.edit")} #${fact.id}` : t(`memory.add.${kind}`)}</DialogTitle>
            <DialogDescription>{kind === "slang" ? t("memory.slangHint") : t("memory.factHint")}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="fact-text">{t("memory.text")}</Label>
            <Textarea id="fact-text" rows={4} autoFocus {...form.register("text")} />
            <div className="flex justify-between text-xs">
              <span className="text-bad">{form.formState.errors.text?.message}</span>
              <span className={len > LIMITS[kind] ? "text-bad" : "text-muted-foreground"}>
                {len}/{LIMITS[kind]}
              </span>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
