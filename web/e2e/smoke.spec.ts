import { readFileSync } from "node:fs";
import { expect, PAGES, RAW_KEY, settle, test } from "./fixtures";

const i18n = {
  en: JSON.parse(readFileSync(new URL("../src/i18n/en.json", import.meta.url), "utf8")),
  lt: JSON.parse(readFileSync(new URL("../src/i18n/lt.json", import.meta.url), "utf8")),
};

for (const { path, nav } of PAGES) {
  test(`${path} renders cleanly`, async ({ page }, info) => {
    const lang = info.project.name.endsWith("-lt") ? "lt" : "en";
    await page.goto(path);
    await settle(page);
    await expect(page.locator("header h1").first()).toHaveText(i18n[lang].nav[nav]);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(RAW_KEY);
    expect(text).not.toContain("undefined");
    expect(text).not.toContain("NaN");
  });
}
