import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { campaignWithData, FROZEN_RECORDS, pageErrors, workbenchUrl, type Opened } from "./fixtures";

// The Prepare panels P3-12 adds (decisions/0015.13): the cleaning rules as forms with a
// preview before applying, and the sensor overview's tables, each from its operation.

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

async function call(page: Page, opened: Opened, path: string, data: unknown) {
  const response = await page.request.post(`/api/sessions/${opened.sessionId}/${path}`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

type Intervals = { channels: Record<string, { flagged_records: number; intervals: Array<{ first: string; last: string }> }> };

const flagged = async (page: Page, opened: Opened): Promise<Intervals> =>
  call(page, opened, "operations/get_flag_intervals", { channels: "Spd_100m" });

async function openTab(page: Page, title: string) {
  await page.locator(".dv-tab", { hasText: title }).click();
}

async function chooseRule(page: Page, rule: string, sensor: string) {
  const panel = page.locator(".gk-rules");
  await panel.getByRole("combobox", { name: "Rule" }).selectOption({ label: rule });
  await panel.getByRole("combobox", { name: "Sensor" }).selectOption(sensor);
  return panel;
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

test("rules applied through the panel flag the records the old form's rules flag", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Rules ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await openTab(page, "Cleaning rules");

  // The three rules the old cleaning form offers: its range and stuck-sensor presets, and the
  // expression that catches the frozen cup (0.35 to 0.43 m/s, the lower cups turning).
  let panel = await chooseRule(page, "range check", "Spd_100m");
  await panel.getByRole("button", { name: "Preview" }).click();
  // The fixture has no value outside the range: the preview says so, and applying logs a rule that flags nothing.
  await expect(panel.getByText(/values would be set missing/)).toBeVisible();
  await panel.getByRole("button", { name: "Apply rule" }).click();
  await expect(panel.getByRole("status")).toContainText("range check on Spd_100m");

  panel = await chooseRule(page, "stuck sensor", "Spd_100m");
  await expect(panel.getByRole("spinbutton", { name: /consecutive count/ })).toHaveValue("6");
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel.getByText(/values would be set missing/)).toBeVisible();
  await panel.getByRole("button", { name: "Apply rule" }).click();
  await expect(panel.getByRole("status")).toContainText("stuck sensor on Spd_100m");

  panel = await chooseRule(page, "expression filter", "Spd_100m");
  await panel.getByRole("textbox", { name: /expression/ }).fill("Spd_100m < 0.5");
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel.getByText(`${FROZEN_RECORDS}`, { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Apply rule" }).click();
  await expect(panel.getByRole("status")).toContainText(`${FROZEN_RECORDS} values set missing`);

  // The twin campaign takes the old form's own requests through the hand-written route it posts to.
  const twin = await campaignWithData(page, `Rules twin ${Date.now()}`);
  const old = { start_date: "", end_date: "" };
  await call(page, twin, "cleaning/apply", { rule_type: "range_check", sensor: "Spd_100m", params: { min: 0, max: 50 }, ...old });
  await call(page, twin, "cleaning/apply", { rule_type: "stuck_sensor", sensor: "Spd_100m", params: { consecutive_count: 6 }, ...old });
  await call(page, twin, "cleaning/apply", { rule_type: "expression_filter", sensor: "Spd_100m", params: { expression: "Spd_100m < 0.5" }, ...old });

  const mine = await flagged(page, opened);
  const theirs = await flagged(page, twin);
  const intervals = (result: Intervals) => result.channels.Spd_100m.intervals.map(({ first, last }) => [first, last]);
  expect(mine.channels.Spd_100m.flagged_records).toBeGreaterThanOrEqual(FROZEN_RECORDS);
  expect(mine.channels.Spd_100m.flagged_records).toBe(theirs.channels.Spd_100m.flagged_records);
  expect(intervals(mine)).toEqual(intervals(theirs));
  const entry = (await call(page, opened, "operations/get_cleaning_log", {})).entries.map((item: { rule_type: string; records_affected: number }) => [item.rule_type, item.records_affected]);
  const twinEntry = (await call(page, twin, "operations/get_cleaning_log", {})).entries.map((item: { rule_type: string; records_affected: number }) => [item.rule_type, item.records_affected]);
  expect(entry).toEqual(twinEntry);

  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("rules-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("rules-dark.png") });
});

test("a preview shows the change before it is applied, and applying draws the flag bands", async ({ page }) => {
  const opened = await campaignWithData(page, `Preview ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.locator(".gk-timeline .u-over")).toBeVisible();
  await openTab(page, "Cleaning rules");
  const panel = await chooseRule(page, "expression filter", "Spd_100m");
  await panel.getByRole("textbox", { name: /expression/ }).fill("Spd_100m < 0.5");

  await expect(panel.getByRole("button", { name: "Apply rule" })).toBeDisabled();
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel.getByRole("list", { name: "Values set missing by column" })).toContainText("Spd_100m:");
  expect((await flagged(page, opened)).channels.Spd_100m.flagged_records).toBe(0);

  // Editing the rule makes the preview stale: it described another request.
  await panel.getByRole("textbox", { name: /expression/ }).fill("Spd_100m < 0.45");
  await expect(panel.getByRole("list", { name: "Values set missing by column" })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "Apply rule" })).toBeDisabled();
  await panel.getByRole("button", { name: "Preview" }).click();
  await panel.getByRole("button", { name: "Apply rule" }).click();
  await expect(panel.getByRole("status")).toContainText("values set missing");

  await expect(page.getByRole("region", { name: "Flags" })).toContainText("Spd_100m");
  expect((await flagged(page, opened)).channels.Spd_100m.flagged_records).toBeGreaterThan(0);
});

test("a refusal shows the server's words", async ({ page }) => {
  const opened = await campaignWithData(page, `Refusal ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await openTab(page, "Cleaning rules");
  const panel = await chooseRule(page, "expression filter", "Spd_100m");
  await panel.getByRole("textbox", { name: /expression/ }).fill("Nothing_here < 1");
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel.getByRole("alert")).toContainText(/Nothing_here|expression|column/i);
});

test("the sensor overview fills each section from its operation and gives a refusal's reason", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Overview ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await openTab(page, "Sensor overview");
  const overview = page.locator(".gk-overview");

  const qc = overview.getByRole("table", { name: "Quality control by sensor" });
  await expect(qc.getByRole("rowheader", { name: "Spd_100m", exact: true })).toBeVisible();
  const served = await call(page, opened, "operations/compute_qc_diagnostics", {});
  const row = qc.getByRole("row", { name: /Spd_100m$|^Spd_100m / }).first();
  await expect(row.getByRole("cell").nth(1)).toHaveText(String(served.sensors.find((s: { sensor: string }) => s.sensor === "Spd_100m").range_failures));

  const comparison = overview.getByRole("region", { name: "Sensor comparison" });
  const compared = await call(page, opened, "operations/compute_sensor_comparison", { sensor_a: "Spd_100m", sensor_b: "Spd_80m" });
  await expect(comparison.getByRole("term").filter({ hasText: "Records" })).toBeVisible();
  await expect(comparison).toContainText(String(compared.record_count));

  // The fixture has no reanalysis reference, no direction pair on a boom and no pressure
  // sensor: those sections say what the server said, not an empty table.
  for (const name of ["MCP readiness", "Atmospheric conditions"]) {
    const section = overview.getByRole("region", { name });
    await expect(section.getByRole("alert")).not.toBeEmpty();
    await expect(section.getByRole("table")).toHaveCount(0);
  }
  const refused = await page.request.post(`/api/sessions/${opened.sessionId}/operations/compute_atmospheric_conditions`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: {},
  });
  expect(refused.ok()).toBeFalsy();
  const reason = (await refused.json()).detail as string;
  await expect(overview.getByRole("region", { name: "Atmospheric conditions" }).getByRole("alert")).toHaveText(reason);

  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("overview-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("overview-dark.png") });
});
