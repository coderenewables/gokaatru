import { expect, test } from "@playwright/test";
import type { ConsoleMessage } from "@playwright/test";

import { newCampaign } from "./fixtures";

// Console errors that are expected with no data loaded. Each entry needs a reason. There
// are none: GET /sensors on an empty session used to answer 400, and now returns an empty
// inventory (P1-18).
const ALLOWED_CONSOLE_ERRORS: Array<{ pattern: RegExp; reason: string }> = [];

// HTTP failures an empty campaign is expected to produce. None.
const EXPECTED_FAILED_RESPONSES: RegExp[] = [];

const PHASE_PANELS: Record<string, string> = {
  Prepare: "Timeline",
  Model: "Pipeline",
  Run: "Sweep design",
  Interrogate: "Scenarios",
};

test("the app loads at /, opens a campaign, moves between phases and reaches the backend through /api", async ({
  page,
}, testInfo) => {
  const pageErrors: Error[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (ALLOWED_CONSOLE_ERRORS.some((entry) => entry.pattern.test(text))) return;
    consoleErrors.push(text);
  });

  const failedResponses: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`);
    }
  });

  const name = `Smoke ${Date.now()}`;
  await newCampaign(page, name);
  await page.goto("/");
  await expect(page).toHaveTitle("GoKaatru — Wind Resource Assessment");
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();
  const card = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name, exact: true }) });
  await card.getByRole("link", { name: "Mast M1" }).click();

  const phases = page.getByRole("navigation", { name: "Phases" });
  for (const [phase, panel] of Object.entries(PHASE_PANELS)) {
    await phases.getByRole("button", { name: phase, exact: true }).click();
    await expect(phases.getByRole("button", { name: phase, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(page.locator(".dv-tab", { hasText: new RegExp(`^${panel}$`) })).toBeVisible();
  }
  await page.screenshot({ path: testInfo.outputPath("first-load.png"), fullPage: true });

  // The brand returns to the start screen.
  await page.getByRole("link", { name: "GoKaatru" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Projects" })).toBeVisible();

  // Same-origin fetch from the page, so it exercises the Vite proxy, not the backend port directly.
  const health = await page.evaluate(async () => {
    const response = await fetch("/api/health");
    return { status: response.status, body: await response.json() };
  });
  expect(health.status).toBe(200);
  expect(health.body).toEqual({ status: "ok", service: "gokaatru-web-api" });

  expect(pageErrors.map((error) => error.message)).toEqual([]);
  // Responses before console errors: a failed request is echoed to the console without its URL.
  const unexpected = failedResponses.filter((entry) => !EXPECTED_FAILED_RESPONSES.some((pattern) => pattern.test(entry)));
  expect(unexpected).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
