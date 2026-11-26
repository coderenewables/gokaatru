import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { campaignWithData, FROZEN_START, pageErrors, RECORDS, workbenchUrl, type Opened } from "./fixtures";

// The flag flow (P2-18, plan §3.3 "Timeline" and "Any flag band"; decisions/0014.1-3):
// brush, flag the whole instrument with a reason after a preview, see the band, inspect it,
// remove it in one click; the drawn flag's records equal the old rule's for the same period.

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

const over = (page: Page) => page.locator(".gk-timeline .u-over");
const inspector = (page: Page) => page.locator(".gk-inspector");

async function brush(page: Page, from: number, to: number) {
  const box = await over(page).boundingBox();
  if (!box) throw new Error("the plot is not drawn");
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * from, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * ((from + to) / 2), y, { steps: 5 });
  await page.mouse.move(box.x + box.width * to, y, { steps: 5 });
  await page.mouse.up();
}

async function call(page: Page, opened: Opened, path: string, data: unknown) {
  const response = await page.request.post(`/api/sessions/${opened.sessionId}/${path}`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

type Intervals = { channels: Record<string, { flagged_records: number; intervals: Array<{ first: string; last: string }> }> };

test("a brushed period flags the whole instrument, shows as a band, and is removed in one click", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Flag ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(over(page)).toBeVisible();
  const from = (FROZEN_START - 10) / (RECORDS - 1);
  const to = (FROZEN_START + 60) / (RECORDS - 1);
  await brush(page, from, to);

  const form = inspector(page).getByRole("region", { name: "Flag the selection" });
  await expect(form.getByRole("combobox", { name: "Instrument" })).toHaveValue("Spd_100m");
  const columns = form.getByRole("group", { name: "Columns set missing" });
  await expect(columns.getByRole("checkbox", { name: "Spd_100m", exact: true })).toBeChecked();
  await expect(columns.getByRole("checkbox", { name: "Spd_100m_sd" })).toBeChecked();
  await expect(form.getByRole("button", { name: "Apply flag" })).toBeDisabled();
  await form.getByRole("combobox", { name: "Reason" }).selectOption("other");
  await expect(form.getByText("needs a note")).toBeVisible();
  await form.getByRole("combobox", { name: "Reason" }).selectOption("icing");
  await form.getByRole("textbox", { name: /Note/ }).fill("Cup frozen, the lower cups turning");
  await form.getByRole("button", { name: "Preview" }).click();
  const changed = form.getByRole("list", { name: "Values set missing by column" });
  await expect(changed).toContainText("Spd_100m:");
  await expect(changed).toContainText("Spd_100m_sd:");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("flag-preview.png") });
  await form.getByRole("button", { name: "Apply flag" }).click();
  await expect(inspector(page).getByRole("status")).toContainText("as icing (rule 1)");
  await expect(page.getByText("Select on any chart.")).toBeVisible();

  // The drawn flag holds exactly the records the old rule holds for the same period: the
  // rule's frozen definition is a half-open period, custom_period_exclude's end is inclusive.
  const log = await call(page, opened, "operations/get_cleaning_log", {});
  const entry = log.entries[0];
  expect(entry.rule_type).toBe("exclude_selection");
  expect(entry.reason).toBe("icing");
  expect(entry.params.note).toBe("Cup frozen, the lower cups turning");
  const period = entry.params.definition as { kind: string; start: string; end: string };
  expect(period.kind).toBe("time_range");
  const drawn = (await call(page, opened, "operations/get_flag_intervals", { channels: "Spd_100m,Spd_100m_sd" })) as Intervals;
  expect(drawn.channels.Spd_100m.flagged_records).toBe(drawn.channels.Spd_100m_sd.flagged_records);
  const twin = await campaignWithData(page, `Flag twin ${Date.now()}`);
  const step = 10 * 60 * 1000;
  const lastInside = new Date(Math.ceil(Date.parse(period.end) / step) * step - step).toISOString().slice(0, 16).replace("T", " ");
  await call(page, twin, "cleaning/apply", {
    rule_type: "custom_period_exclude",
    sensor: "Spd_100m",
    params: {},
    start_date: new Date(Math.ceil(Date.parse(period.start) / step) * step).toISOString().slice(0, 16).replace("T", " "),
    end_date: lastInside,
  });
  const typed = (await call(page, twin, "operations/get_flag_intervals", { channels: "Spd_100m" })) as Intervals;
  expect(drawn.channels.Spd_100m.intervals.map(({ first, last }) => [first, last])).toEqual(
    typed.channels.Spd_100m.intervals.map(({ first, last }) => [first, last]),
  );
  expect(drawn.channels.Spd_100m.flagged_records).toBe(typed.channels.Spd_100m.flagged_records);

  // The band, inspected and removed.
  await expect(page.getByRole("region", { name: "Flags" })).toContainText("Spd_100m");
  const box = await over(page).boundingBox();
  if (!box) throw new Error("the plot is not drawn");
  await page.mouse.click(box.x + (box.width * (FROZEN_START + 24)) / (RECORDS - 1), box.y + box.height / 2);
  const focused = inspector(page).getByRole("region", { name: "Flag on Spd_100m" });
  await expect(focused).toContainText("Icing");
  await expect(focused).toContainText("By");
  await expect(focused).toContainText("user");
  await expect(focused).toContainText("Cup frozen, the lower cups turning");
  await page.screenshot({ path: testInfo.outputPath("flag-focused.png") });
  await focused.getByRole("button", { name: "Remove rule 1" }).click();
  await expect(page.getByRole("region", { name: "Flags" })).toContainText("No records flagged.");
});

test("rose sectors become a tower-shadow rule, previewed then applied", async ({ page }) => {
  const opened = await campaignWithData(page, `Shadow ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const sectors = page.getByRole("group", { name: "Sectors" });
  const make = page.getByRole("button", { name: "Make a tower-shadow rule" });
  await sectors.getByRole("button", { name: "W", exact: true }).click();
  await sectors.getByRole("button", { name: "120°" }).click({ modifiers: ["Shift"] });
  await expect(make).toBeDisabled();
  await sectors.getByRole("button", { name: "120°" }).click({ modifiers: ["Shift"] });
  await sectors.getByRole("button", { name: "240°" }).click({ modifiers: ["Shift"] });
  await make.click();
  const proposed = inspector(page).getByRole("region", { name: "Proposed rule" });
  await expect(proposed).toContainText("Tower shadow on Spd_100m: directions 225° to 285°");
  await proposed.getByRole("button", { name: "Preview" }).click();
  await expect(proposed.getByRole("list", { name: "Values set missing by column" })).toContainText("Spd_100m:");
  await proposed.getByRole("button", { name: "Apply rule" }).click();
  await expect(proposed).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Flags" })).toContainText("tower shadow");

  const twin = await campaignWithData(page, `Shadow twin ${Date.now()}`);
  await call(page, twin, "cleaning/apply", {
    rule_type: "tower_shadow",
    sensor: "Spd_100m",
    params: { exclude_sectors: [225, 285] },
    start_date: "",
    end_date: "",
  });
  const drawn = (await call(page, opened, "operations/get_flag_intervals", { channels: "Spd_100m" })) as Intervals;
  const typed = (await call(page, twin, "operations/get_flag_intervals", { channels: "Spd_100m" })) as Intervals;
  const records = (result: Intervals) => result.channels.Spd_100m.intervals.map(({ first, last }) => [first, last]);
  expect(drawn.channels.Spd_100m.flagged_records).toBeGreaterThan(0);
  expect(drawn.channels.Spd_100m.flagged_records).toBe(typed.channels.Spd_100m.flagged_records);
  expect(records(drawn)).toEqual(records(typed));
});
