"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, post } from "@/lib/api";
import { useT } from "@/lib/i18n";

// same ranges as the API (botucha/webapi/routes_settings.py)
const NUMBERS: [string, number, number, boolean][] = [
  ["model.temperature", 0, 2, false],
  ["model.min_p", 0, 1, false],
  ["model.num_predict", 16, 2048, true],
  ["trigger.keyword_prob", 0, 1, false],
  ["trigger.random_n", 2, 10_000, true],
  ["trigger.cooldown_s", 0, 86_400, true],
  ["trigger.reaction_n", 1, 10_000, true],
  ["trigger.tyla_default_min", 0, 10_080, true],
  ["trigger.user_calls_per_min", 1, 1_000, true],
  ["trigger.burst_quiet_s", 0.1, 600, false],
  ["trigger.burst_max_s", 0.1, 3_600, false],
];
const field = (k: string) => k.replace(".", "_");

const schema = z.object({
  ...Object.fromEntries(
    NUMBERS.map(([k, lo, hi, int]) => {
      let n = z.number().min(lo).max(hi);
      if (int) n = n.int();
      // an empty field is an error, not 0 (0 calls per minute would silence the bot)
      return [field(k), z.preprocess((v) => (v === "" || v == null ? undefined : Number(v)), n)];
    }),
  ),
  trigger_keywords: z.string().trim().min(1),
});
type Values = Record<string, string | number>;

export function ConfigForm() {
  const t = useT();
  const [error, setError] = useState("");
  const form = useForm<Values>({ resolver: zodResolver(schema) as never });
  useEffect(() => {
    api<{ values: Record<string, number | string[]> }>("/api/config")
      .then(({ values }) => {
        const v: Values = {};
        for (const [k, val] of Object.entries(values)) v[field(k)] = Array.isArray(val) ? val.join(", ") : val;
        form.reset(v);
      })
      .catch(() => {});
  }, [form]);

  const submit = form.handleSubmit(async (v) => {
    const values: Record<string, unknown> = Object.fromEntries(NUMBERS.map(([k]) => [k, Number(v[field(k)])]));
    values["trigger.keywords"] = String(v.trigger_keywords)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await post("/api/config", { values }, "PUT", { inline: [422] });
      setError("");
      toast.success(t("common.saved"), {
        action: {
          label: t("settings.restartNow"),
          onClick: () =>
            post("/api/control/service", { action: "restart" })
              .then(() => toast.success(t("controls.done")))
              .catch(() => {}),
        },
        duration: 15_000,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.config")}</CardTitle>
        <CardDescription>{t("settings.configHint")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form noValidate onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="trigger_keywords">{t("settings.fields.trigger_keywords")}</Label>
            <Input id="trigger_keywords" {...form.register("trigger_keywords")} />
            <p className="text-muted-foreground text-xs">{t("settings.hints.trigger_keywords")}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {NUMBERS.map(([k, lo, hi, int]) => (
              <div key={k} className="flex flex-col gap-1.5">
                <Label htmlFor={field(k)}>{t(`settings.fields.${field(k)}`)}</Label>
                <Input
                  id={field(k)}
                  type="number"
                  step={int ? 1 : "any"}
                  min={lo}
                  max={hi}
                  {...form.register(field(k))}
                />
                {form.formState.errors[field(k)] ? (
                  <p className="text-bad text-xs">
                    {lo} – {hi}
                  </p>
                ) : k === "model.temperature" || k === "model.min_p" ? (
                  <p className="text-muted-foreground text-xs">{t(`settings.hints.${field(k)}`)}</p>
                ) : null}
              </div>
            ))}
          </div>
          {error ? <p className="text-bad text-sm">{error}</p> : null}
          <Button type="submit" className="self-start" disabled={form.formState.isSubmitting}>
            {t("common.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
