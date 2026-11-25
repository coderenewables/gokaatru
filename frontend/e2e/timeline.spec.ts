import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { campaignWithData, FROZEN_START, RECORDS, workbenchUrl } from "./fixtures";

// The timeline panel (P2-14, plan §3.3 "Timeline" and "Any chart"): envelopes by default,
// brushing into the crossfilter, flag bands, and the channel picker.

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

const plot = (page: Page) => page.getByRole("img", { name: /^Timeline of/ });
const over = (page: Page) => page.locator(".gk-timeline .u-over");
const legend = (page: Page) => page.getByRole("list", { name: "Timeline channels" });
const terms = (page: Page) => page.getByRole("list", { name: "Selection terms" });
const count = (page: Page) => page.locator(".gk-selection-count strong");

async function drag(page: Page, from: number, to: number, shift = false) {
  const box = await over(page).boundingBox();
  if (!box) throw new Error("the plot is not drawn");
  const y = box.y + box.height / 2;
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.move(box.x + box.width * from, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * ((from + to) / 2), y, { steps: 5 });
  await page.mouse.move(box.x + box.width * to, y, { steps: 5 });
  await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
}

async function selectedRecords(locator: Locator): Promise<number> {
  await expect(locator).toHaveText(/^\d+$/);
  return Number(await locator.innerText());
}

async function open(page: Page, name: string) {
  const opened = await campaignWithData(page, `${name} ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(plot(page)).toBeVisible();
  await expect(legend(page).getByRole("listitem")).toHaveCount(3);
  return opened;
}

test("the timeline shows the three speeds by default and passes axe", async ({ page }, testInfo) => {
  await open(page, "Timeline default");
  for (const channel of ["Spd_100m", "Spd_80m", "Spd_60m"]) {
    await expect(legend(page)).toContainText(channel);
  }
  await expect(plot(page)).toHaveAttribute("aria-label", /Spd_100m, Spd_80m, Spd_60m, 2023-03-01 00:00 to/);
  await expect(over(page)).toBeVisible();
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("timeline-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(legend(page).getByRole("listitem")).toHaveCount(3);
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("timeline-dark.png") });
});

test("brushing selects periods, shift adds one and Escape clears", async ({ page }) => {
  await open(page, "Timeline brush");
  await drag(page, 0.2, 0.3);
  await expect(terms(page).getByRole("listitem").filter({ hasText: "Period" })).toHaveCount(1);
  const first = await selectedRecords(count(page));
  expect(first).toBeGreaterThan(0);
  expect(first).toBeLessThan(RECORDS);

  await drag(page, 0.6, 0.7, true);
  await expect.poll(async () => Number(await count(page).innerText())).toBeGreaterThan(first);
  expect(await selectedRecords(count(page))).toBeLessThan(RECORDS);
  await expect(terms(page).getByRole("listitem")).toHaveCount(1);

  await plot(page).focus();
  await page.keyboard.press("Escape");
  await expect(terms(page)).toHaveCount(0);
});

test("a flag shows as a band and a click on it is announced", async ({ page }) => {
  const opened = await campaignWithData(page, `Timeline flag ${Date.now()}`);
  const applied = await page.request.post(`/api/sessions/${opened.sessionId}/operations/apply_cleaning_rule`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: {
      rule_type: "custom_period_exclude",
      sensor: "Spd_100m",
      params: "{}",
      start_date: "2023-03-14 21:20",
      end_date: "2023-03-15 05:10",
    },
  });
  expect(applied.ok(), await applied.text()).toBeTruthy();
  const flagged = page.waitForResponse((response) => response.url().includes("get_flag_intervals") && response.ok());
  await page.goto(workbenchUrl(opened));
  await expect(plot(page)).toBeVisible();
  await flagged;
  const box = await over(page).boundingBox();
  if (!box) throw new Error("the plot is not drawn");
  // The record's x is its index across the whole record, so the band's middle is known.
  const x = box.x + (box.width * (FROZEN_START + 24)) / (RECORDS - 1);
  await page.mouse.click(x, box.y + box.height / 2);
  await expect(page.locator(".gk-timeline-status")).toHaveText(
    "Spd_100m flagged 2023-03-14 21:20 to 2023-03-15 05:10 UTC, 48 records, excluded_period, custom_period_exclude, by user",
  );
});

test("a channel added through the picker joins the legend and its button removes it", async ({ page }) => {
  await open(page, "Timeline picker");
  await page.getByLabel("Channel to add").selectOption("Tmp_100m");
  await page.getByRole("button", { name: "Add channel" }).click();
  await expect(legend(page).getByRole("listitem")).toHaveCount(4);
  await expect(legend(page)).toContainText("Tmp_100m");
  await expect(plot(page)).toHaveAttribute("aria-label", /Tmp_100m/);
  await page.getByRole("button", { name: "Remove Tmp_100m from the timeline" }).click();
  await expect(legend(page)).not.toContainText("Tmp_100m");
  await expect(legend(page).getByRole("listitem")).toHaveCount(3);
});

test("zooming to the selection refetches the window and the whole record returns", async ({ page }) => {
  await open(page, "Timeline zoom");
  await drag(page, 0.4, 0.5);
  const refetched = page.waitForRequest((request) => request.url().includes("/series") && /"start":"2023/.test(request.postData() ?? ""));
  await page.getByRole("button", { name: "Zoom to selection" }).click();
  await refetched;
  await expect(page.getByRole("button", { name: "Whole record" })).toBeEnabled();
  await page.getByRole("button", { name: "Whole record" }).click();
  await expect(page.getByRole("button", { name: "Whole record" })).toBeDisabled();
});
