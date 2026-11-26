import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl, type Opened } from "./fixtures";

// Global undo and redo, the command palette and the arrow keys through flags (P2-19, plan
// §3.3 "Anywhere"), and the status bar beside them.

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

const status = (page: Page) => page.getByRole("contentinfo", { name: "Status" });
const flags = (page: Page) => page.getByRole("region", { name: "Flags" });

async function flag(page: Page, opened: Opened, start: string, end: string) {
  const response = await page.request.post(`/api/sessions/${opened.sessionId}/operations/apply_cleaning_rule`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: { rule_type: "custom_period_exclude", sensor: "Spd_100m", params: "{}", start_date: start, end_date: end },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test("Ctrl+Z undoes the last change and Ctrl+Shift+Z redoes it, with the status bar following", async ({ page }) => {
  const opened = await campaignWithData(page, `Undo ${Date.now()}`);
  await flag(page, opened, "2023-03-14 21:20", "2023-03-15 05:10");
  await page.goto(workbenchUrl(opened));
  await expect(flags(page)).toContainText("Spd_100m 48 records");
  await expect(status(page)).toContainText(/\d+ actions/);
  await expect(status(page)).toContainText(/data version \d+/);
  await expect(status(page)).toContainText(/prefix [0-9a-f]{8}/);
  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();

  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z");
  await expect(status(page)).toContainText("Undid apply cleaning rule (custom_period_exclude).");
  await expect(flags(page)).toContainText("No records flagged.");
  await expect(page.getByRole("button", { name: "Redo" })).toBeEnabled();

  await page.keyboard.press("Control+Shift+z");
  await expect(status(page)).toContainText("Redid apply cleaning rule (custom_period_exclude).");
  await expect(flags(page)).toContainText("Spd_100m 48 records");
  await expect(page.getByRole("button", { name: "Redo" })).toBeDisabled();
});

test("Ctrl+K finds a command by name, and brings back a closed panel", async ({ page }) => {
  const opened = await campaignWithData(page, `Palette ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await page.getByRole("button", { name: "Close Profile" }).click();
  await expect(page.locator(".dv-tab", { hasText: "Profile" })).toHaveCount(0);

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Commands" });
  await expect(palette).toBeVisible();
  const results = await new AxeBuilder({ page }).include(".gk-palette").analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.keyboard.type("profile");
  await expect(palette.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(palette).toHaveCount(0);
  await expect(page.locator(".dv-tab", { hasText: "Profile" })).toBeVisible();

  await page.keyboard.press("Control+k");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Commands" })).toHaveCount(0);
});

test("the arrow keys step through the flags on the timeline", async ({ page }) => {
  const opened = await campaignWithData(page, `Arrows ${Date.now()}`);
  await flag(page, opened, "2023-03-05 00:00", "2023-03-05 02:00");
  await flag(page, opened, "2023-03-14 21:20", "2023-03-15 05:10");
  const loaded = page.waitForResponse((response) => response.url().includes("get_flag_intervals") && response.ok());
  await page.goto(workbenchUrl(opened));
  await loaded;
  const timeline = page.getByRole("img", { name: /^Timeline of/ });
  await timeline.focus();
  const focused = page.getByRole("region", { name: "Flag on Spd_100m" });
  await page.keyboard.press("ArrowRight");
  await expect(focused).toContainText("13, 2023-03-05 00:00 UTC to 2023-03-05 02:00 UTC");
  await page.keyboard.press("ArrowRight");
  await expect(focused).toContainText("48, 2023-03-14 21:20 UTC to 2023-03-15 05:10 UTC");
  await page.keyboard.press("ArrowLeft");
  await expect(focused).toContainText("13, 2023-03-05 00:00 UTC");
  await expect(page.locator(".gk-timeline-status")).toContainText("Spd_100m flagged 2023-03-05 00:00");
});
