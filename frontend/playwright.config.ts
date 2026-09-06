import { defineConfig, devices } from "@playwright/test";

/**
 * The journey runs against the compose stack, not against a dev server: it signs in
 * through Django's own login page, so the SPA is exercised with a real session cookie.
 *
 * E2E_BASE_URL points at that stack. Without it the journey skips rather than failing —
 * see tests/e2e/journey.spec.ts.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
