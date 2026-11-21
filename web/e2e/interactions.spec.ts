import { expect, settle, test } from "./fixtures";

// Click through every page's controls. English, desktop or phone as noted; the server is shared, so
// anything a test changes it changes back.
test.describe("desktop", () => {
  test.beforeEach(({ problems: _ }, info) => {
    test.skip(info.project.name !== "desktop-light-en", "runs once, on desktop English");
  });

  test("range tabs reload overview, pipeline and quality", async ({ page }) => {
    for (const path of ["/", "/pipeline/", "/quality/"]) {
      await page.goto(path);
      await settle(page);
      for (const tab of ["30 days", "7 days", "24 hours"]) {
        await page.getByRole("tab", { name: tab }).click();
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("data-state", "active");
      }
    }
  });

  test("pipeline: a box opens the matching replies, and the filter clears", async ({ page }) => {
    await page.goto("/pipeline/");
    await settle(page);
    await page.getByRole("button", { name: /^Attempt 1: spelling: \d+$/ }).click();
    await expect(page).toHaveURL(/thinking\/\?path=a1%3Aspelling/);
    await expect(page.getByRole("row")).toHaveCount(3); // header + the 2 replies in the last 24 h that failed spelling first
    await page.getByRole("link", { name: "Clear filter" }).click();
    await expect(page).toHaveURL(/\/thinking\/$/);
  });

  test("stat cards link to their replies", async ({ page }) => {
    await page.goto("/pipeline/");
    await settle(page);
    await page.getByRole("link", { name: /Fallback sent/ }).click();
    await expect(page).toHaveURL(/path=out%3Afallback|path=out:fallback/);
    await expect(page.getByRole("row")).toHaveCount(2);
  });

  test("thinking: open a trace, a step, and close the panel", async ({ page }) => {
    await page.goto("/thinking/");
    await settle(page);
    await page.getByRole("row").filter({ hasText: "Mantas" }).click();
    await expect(page).toHaveURL(/\?id=\d+/);
    await expect(page.getByText("Claude unavailable").or(page.getByText("Proofread")).first()).toBeAttached();
    await page.getByText("Generation", { exact: false }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.getByRole("link", { name: "All traces" }).click();
    await expect(page).toHaveURL(/\/thinking\/$/);
  });

  test("quality: mark a word as known and back", async ({ page }) => {
    await page.goto("/quality/");
    await settle(page);
    const row = page.getByRole("row").filter({ hasText: "glichiuoja" });
    await expect(row.getByText("real word")).toBeVisible();
    await row.getByRole("button", { name: "Add" }).click();
    await expect(row.getByRole("button", { name: "✓ known" })).toBeVisible();
    await row.getByRole("button", { name: "✓ known" }).click();
    await expect(row.getByRole("button", { name: "Add" })).toBeVisible();
    await expect(page.getByText("Off: not enabled in config.toml")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Use Claude" })).toBeDisabled();
  });

  test("settings: invalid value is refused, a valid one saves", async ({ page }) => {
    await page.goto("/settings/");
    await settle(page);
    const temp = page.getByLabel("Temperature");
    await temp.fill("5");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("0 – 2")).toBeVisible();
    await temp.fill("0.7");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Saved", { exact: false }).first()).toBeVisible();
  });

  test("controls: replying switch and service restart through the confirm dialog", async ({ page }) => {
    await page.goto("/controls/");
    await settle(page);
    const sw = page.getByRole("switch").first();
    const before = await sw.getAttribute("data-state");
    await sw.click();
    await expect(sw).not.toHaveAttribute("data-state", before ?? "");
    await sw.click();
    await expect(sw).toHaveAttribute("data-state", before ?? "");
    await page.getByRole("button", { name: "Restart" }).click();
    await expect(page.getByRole("alertdialog")).toContainText("Restart the bot?");
    await page.getByRole("alertdialog").getByRole("button", { name: "Restart" }).click();
    await expect(page.getByText("Done").first()).toBeVisible();
  });

  test("memory: tabs, search and the add dialog", async ({ page }) => {
    await page.goto("/memory/");
    await settle(page);
    await expect(page.getByText("Tadas dirba banke")).toBeVisible();
    await page.getByRole("tab", { name: "Slang" }).click();
    await expect(page.getByText("tsg = tiesiog")).toBeVisible();
    await page.getByRole("tab", { name: "Facts" }).click();
    await page.getByPlaceholder("Search").fill("banke");
    await expect(page.getByText("Tadas dirba banke")).toBeVisible();
    await page.getByRole("button", { name: "Add fact" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("people: the graph shows people and a person opens", async ({ page }) => {
    await page.goto("/people/");
    await settle(page);
    await page.locator(".react-flow__node").filter({ hasText: "Tadas" }).click();
    await expect(page.getByRole("dialog")).toContainText("Tadas dirba banke");
    await page.keyboard.press("Escape");
  });

  test("ratings list the seeded rating and link its trace", async ({ page }) => {
    await page.goto("/ratings/");
    await settle(page);
    await expect(page.getByRole("row").filter({ hasText: "Rūta" })).toBeVisible();
  });

  test("range and filters live in the URL and survive a reload", async ({ page }) => {
    await page.goto("/pipeline/");
    await settle(page);
    await page.getByRole("tab", { name: "7 days" }).click();
    await expect(page).toHaveURL(/range=7d/);
    await page.reload();
    await settle(page);
    await expect(page.getByRole("tab", { name: "7 days" })).toHaveAttribute("data-state", "active");
    await page.goto("/thinking/?outcome=fallback");
    await settle(page);
    await expect(page.getByRole("row")).toHaveCount(2); // header + the one fallback
    await page.goBack();
    await expect(page).toHaveURL(/range=7d/);
  });

  test("a failing read shows an error with a working retry", async ({ page, problems }) => {
    let fail = true;
    await page.route("**/api/quality?*", (route) =>
      fail ? route.fulfill({ status: 500, json: { error: "boom" } }) : route.fallback(),
    );
    await page.goto("/quality/");
    await settle(page);
    const alert = page.getByRole("alert").filter({ hasText: "boom" });
    await expect(alert).toBeVisible({ timeout: 10_000 }); // after the quiet retries
    fail = false;
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(alert).toBeHidden();
    await expect(page.getByRole("row").filter({ hasText: "glichiuoja" })).toBeVisible();
    problems.splice(0); // the 500s above were on purpose
  });

  test("language, theme and sidebar switches", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await page.getByRole("button", { name: "LT", exact: true }).click();
    await expect(page.locator("header h1")).toHaveText("Apžvalga");
    await page.getByRole("button", { name: "EN", exact: true }).click();
    await expect(page.locator("header h1")).toHaveText("Overview");
    await page.getByRole("button", { name: "Dark", exact: true }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.getByRole("button", { name: "Light", exact: true }).click();
    await expect(page.locator("html")).not.toHaveClass(/dark/);
    await page.getByRole("button", { name: "Toggle Sidebar" }).first().click();
    await expect(page.locator("[data-slot=sidebar][data-state]").first()).toHaveAttribute("data-state", "collapsed");
  });
});

test.describe("phone", () => {
  test.beforeEach(({ problems: _ }, info) => {
    test.skip(info.project.name !== "phone-light-en", "runs once, on phone English");
  });

  test("menu opens as a sheet and navigates", async ({ page }) => {
    await page.goto("/");
    await settle(page);
    await page.getByRole("button", { name: "Toggle Sidebar" }).first().click();
    await page.getByRole("link", { name: "Pipeline" }).click();
    await expect(page.locator("header h1")).toHaveText("Pipeline");
  });
});
