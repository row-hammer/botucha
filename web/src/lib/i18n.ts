"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import en from "@/i18n/en.json";
import lt from "@/i18n/lt.json";

export type Lang = "en" | "lt";
type Dict = Record<string, unknown>;
const dicts: Record<Lang, Dict> = { en, lt };

const safeStorage = createJSONStorage(() => ({
  getItem: (k: string) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  setItem: (k: string, v: string) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* private window: keep the choice for this visit only */
    }
  },
  removeItem: (k: string) => {
    try {
      localStorage.removeItem(k);
    } catch {
      /* ignore */
    }
  },
}));

export const useLang = create<{ lang: Lang; setLang: (l: Lang) => void }>()(
  persist((set) => ({ lang: "en", setLang: (lang) => set({ lang }) }), { name: "botucha.lang", storage: safeStorage }),
);

function lookup(dict: Dict, key: string): string | undefined {
  let cur: unknown = dict;
  for (const part of key.split(".")) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Dict)[part];
  }
  return typeof cur === "string" ? cur : undefined;
}

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const text = lookup(dicts[lang], key) ?? lookup(dicts.en, key) ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (_, v) => String(vars[v] ?? `{${v}}`)) : text;
}

export function useT() {
  const lang = useLang((s) => s.lang);
  return (key: string, vars?: Record<string, string | number>) => translate(lang, key, vars);
}

export function useLocale(): string {
  return useLang((s) => s.lang) === "lt" ? "lt-LT" : "en-GB";
}
