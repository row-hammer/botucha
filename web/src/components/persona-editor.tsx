"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Line = { type: "same" | "add" | "del"; text: string };

/** Line diff by longest common subsequence: fine for a few hundred lines. */
export function lineDiff(a: string, b: string): Line[] {
  const x = a.split("\n");
  const y = b.split("\n");
  const m = x.length;
  const n = y.length;
  const L = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Line[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (x[i] === y[j]) {
      out.push({ type: "same", text: x[i] });
      i++;
      j++;
    } else if (L[i + 1][j] >= L[i][j + 1]) out.push({ type: "del", text: x[i++] });
    else out.push({ type: "add", text: y[j++] });
  }
  while (i < m) out.push({ type: "del", text: x[i++] });
  while (j < n) out.push({ type: "add", text: y[j++] });
  return out;
}

export function PersonaEditor() {
  const t = useT();
  const [saved, setSaved] = useState("");
  const [text, setText] = useState("");
  const [limit, setLimit] = useState(0);
  const [review, setReview] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ text: string; limit: number }>("/api/persona")
      .then((r) => {
        setSaved(r.text);
        setText(r.text);
        setLimit(r.limit);
      })
      .catch(() => {});
  }, []);
  const diff = useMemo(() => (review ? lineDiff(saved, text) : []), [review, saved, text]);
  const changed = diff.filter((d) => d.type !== "same");

  const save = async () => {
    try {
      await post("/api/persona", { text }, "PUT");
      setSaved(text);
      setReview(false);
      setError("");
      toast.success(t("common.saved"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.persona")}</CardTitle>
        <CardDescription>{t("settings.personaHint")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <Textarea
          className="min-h-[28rem] font-mono text-xs leading-relaxed"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
        <div className="flex items-center gap-2">
          <span className={cn("text-xs", text.length > limit ? "text-bad" : "text-muted-foreground")}>
            {t("settings.chars", { n: text.length, max: limit })}
          </span>
          {error ? <span className="text-bad text-xs">{error}</span> : null}
          <Button
            className="ml-auto"
            size="sm"
            variant="outline"
            disabled={text === saved}
            onClick={() => setText(saved)}
          >
            {t("common.cancel")}
          </Button>
          <Button size="sm" disabled={text === saved || !text.trim()} onClick={() => setReview(true)}>
            {t("settings.review")}
          </Button>
        </div>
      </CardContent>
      <Dialog open={review} onOpenChange={setReview}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("settings.diff")}</DialogTitle>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md border font-mono text-xs">
            {changed.length === 0
              ? t("settings.noChanges")
              : diff.map((d, i) => (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: diff lines have no identity besides position
                    key={i}
                    className={cn(
                      "whitespace-pre-wrap px-3",
                      d.type === "add" && "bg-ok/15 text-ok",
                      d.type === "del" && "bg-bad/15 text-bad line-through",
                      d.type === "same" && "text-muted-foreground",
                    )}
                  >
                    {d.type === "add" ? "+ " : d.type === "del" ? "− " : "  "}
                    {d.text || " "}
                  </div>
                ))}
          </pre>
          {error ? <p className="text-bad text-sm">{error}</p> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setReview(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={save} disabled={changed.length === 0}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
