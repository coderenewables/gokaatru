import { expect, test } from "@playwright/test";
import type { ConsoleMessage } from "@playwright/test";

// Console errors that are expected with no data loaded. Each entry needs a reason. There
// are none: GET /sensors on an empty session used to answer 400, and now returns an empty
// inventory (P1-18).
const ALLOWED_CONSOLE_ERRORS: Array<{ pattern: RegExp; reason: string }> = [];

// HTTP failures an empty session is expected to produce. None.
const EXPECTED_FAILED_RESPONSES: RegExp[] = [];

test("the app loads, navigates between phases and reaches the backend through /api", async ({ page }, testInfo) => {
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
  await page.goto("/");
  // First load is the pre-session landing page; a session is needed for the rail.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every defensible scenario");
  await page.getByRole("button", { name: "Start workspace" }).click();

  const rail = page.getByRole("navigation", { name: "Primary view" });
  for (const name of ["Prepare", "Run", "Interrogate", "Canvas", "Copilot"]) {
    await expect(rail.getByRole("button", { name })).toBeVisible();
  }

  await expect(page.getByRole("heading", { name: "Everything the scenarios will share" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("first-load.png"), fullPage: true });

  await rail.getByRole("button", { name: "Run" }).click();
  await expect(rail.getByRole("button", { name: "Run" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Run sweep" })).toBeVisible();

  await rail.getByRole("button", { name: "Interrogate" }).click();
  await expect(rail.getByRole("button", { name: "Interrogate" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Run a sweep, or open a saved one, to summarise its spread.")).toBeVisible();

  await rail.getByRole("button", { name: "Prepare" }).click();
  await expect(page.getByRole("heading", { name: "Everything the scenarios will share" })).toBeVisible();

  // Same-origin fetch from the page, so it exercises the Vite proxy, not the backend port directly.
  const health = await page.evaluate(async () => {
    const response = await fetch("/api/health");
    return { status: response.status, body: await response.json() };
  });
  expect(health.status).toBe(200);
  expect(health.body).toEqual({ status: "ok", service: "gokaatru-web-api" });

  expect(pageErrors.map((error) => error.message)).toEqual([]);
  expect(consoleErrors).toEqual([]);
  const unexpected = failedResponses.filter((entry) => !EXPECTED_FAILED_RESPONSES.some((pattern) => pattern.test(entry)));
  expect(unexpected).toEqual([]);
});
