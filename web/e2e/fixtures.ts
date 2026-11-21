import { test as base, expect, type Page } from "@playwright/test";

/** Each test fails on any console error, uncaught exception or failed API call. Language comes from the
 * project name (…-lt), theme from the project's colorScheme. */
export const test = base.extend<{ problems: string[] }>({
  problems: [
    async ({ page }, use, info) => {
      const problems: string[] = [];
      const lang = info.project.name.endsWith("-lt") ? "lt" : "en";
      await page.addInitScript((l) => {
        try {
          localStorage.setItem("botucha.lang", JSON.stringify({ state: { lang: l }, version: 0 }));
        } catch {}
      }, lang);
      page.on("console", (m) => {
        if (m.type() === "error") problems.push(`console: ${m.text()} (${m.location().url})`);
      });
      page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
      page.on("response", (r) => {
        if (r.url().includes("/api/") && r.status() >= 400 && !r.url().includes("/api/live"))
          problems.push(`http ${r.status()}: ${r.url()}`);
      });
      await use(problems);
      expect(problems, "console errors, page errors or failed API calls").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export const PAGES = [
  { path: "/", nav: "overview" },
  { path: "/pipeline/", nav: "pipeline" },
  { path: "/quality/", nav: "quality" },
  { path: "/thinking/", nav: "thinking" },
  { path: "/memory/", nav: "memory" },
  { path: "/people/", nav: "people" },
  { path: "/ratings/", nav: "ratings" },
  { path: "/controls/", nav: "controls" },
  { path: "/settings/", nav: "settings" },
] as const;

// "networkidle" never comes: the live event stream keeps one request open. Wait for the header and data.
export async function settle(page: Page) {
  await page.waitForLoadState("load");
  await page.locator("header h1").first().waitFor();
  await page.waitForTimeout(800);
}

/** Text that looks like an untranslated i18n key, e.g. "quality.words.add". */
export const RAW_KEY = /\b(?:nav|common|overview|pipeline|quality|thinking|memory|people|ratings|controls|settings|checks|step|status|units)\.[a-z][A-Za-z_]*(?:\.[A-Za-z_]+)*\b/;
