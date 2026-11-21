import { defineConfig, devices } from "@playwright/test";

// Smoke tests for the dashboard. They run against web/e2e/server.py: the real API and the built UI
// (`npm run build:static` first) over a throwaway database of invented data, with a fake systemd.
const PORT = 8799;
const chromium = { executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium" };

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  workers: 4,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, launchOptions: chromium, trace: "retain-on-failure" },
  webServer: {
    command: `uv run python web/e2e/server.py --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/session`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: "desktop-light-en", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } },
    {
      name: "desktop-dark-lt",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 }, colorScheme: "dark" },
    },
    { name: "phone-dark-lt", use: { ...devices["Pixel 7"], colorScheme: "dark" } },
    { name: "phone-light-en", use: { ...devices["Pixel 7"] } },
  ],
});
