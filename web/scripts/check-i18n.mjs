// Every UI string must exist in both languages: exits 1 and lists the keys missing on either side.
import { readFileSync } from "node:fs";

const flat = (obj, prefix = "") =>
  Object.entries(obj).flatMap(([k, v]) => (v && typeof v === "object" ? flat(v, `${prefix}${k}.`) : [`${prefix}${k}`]));
const load = (lang) => new Set(flat(JSON.parse(readFileSync(new URL(`../src/i18n/${lang}.json`, import.meta.url)))));
const en = load("en");
const lt = load("lt");
const missing = [
  ...[...en].filter((k) => !lt.has(k)).map((k) => `lt: ${k}`),
  ...[...lt].filter((k) => !en.has(k)).map((k) => `en: ${k}`),
];
if (missing.length) {
  console.error(`missing translations:\n${missing.join("\n")}`);
  process.exit(1);
}
console.log(`i18n ok: ${en.size} keys`);
