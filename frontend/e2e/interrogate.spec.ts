import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { newCampaign, pageErrors } from "./fixtures";
import { stubSweeps, type FakeRow } from "./sweepRows";

// Interrogate's scenario views (P3-14, decisions/0015.7): the scenarios table, the metric's
// histogram and the parallel coordinates, linked as Prepare's charts are: each holds one term
// and the scenarios shown are their intersection. A real sweep cannot run in a browser test,
// so the sweep routes are faked with a fixture of 24 scenarios (e2e/sweepRows.ts).

test.use({ viewport: { width: 1600, height: 1000 } });

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

const scenarios = (page: Page) => page.locator(".gk-interrogate", { has: page.getByLabel("Sweep", { exact: true }) });
const tableRows = (page: Page) => scenarios(page).getByRole("table").locator("tbody tr");
const histogram = (page: Page) => page.getByRole("img", { name: /^Histogram of/ });
const parallel = (page: Page) => page.getByRole("img", { name: /^Parallel coordinates/ });
const terms = (page: Page) => page.getByRole("list", { name: "Scenario terms" });

async function open(page: Page): Promise<{ rows: FakeRow[]; newer: string }> {
  const stub = await stubSweeps(page);
  const campaign = await newCampaign(page, `Interrogate ${Date.now()}`);
  await page.goto(`/?project=${campaign.projectId}&campaign=${campaign.sessionId}&phase=interrogate`);
  await expect(scenarios(page).getByLabel("Sweep", { exact: true })).toBeVisible();
  return stub;
}

async function chooseSweep(page: Page, id: string) {
  await scenarios(page).getByLabel("Sweep", { exact: true }).selectOption(id);
  await expect(histogram(page)).toBeVisible();
  await expect(parallel(page)).toBeVisible();
}

async function drag(page: Page, svg: Locator, from: { x: number; y: number }, to: { x: number; y: number }, shift = false) {
  const box = await svg.boundingBox();
  if (!box) throw new Error("nothing to brush");
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.move(box.x + from.x, box.y + from.y);
  await page.mouse.down();
  await page.mouse.move(box.x + (from.x + to.x) / 2, box.y + (from.y + to.y) / 2, { steps: 5 });
  await page.mouse.move(box.x + to.x, box.y + to.y, { steps: 5 });
  await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
}

const inFilter = (rows: FakeRow[], admissibleOnly = true) => rows.filter((row) => row.admissible || !admissibleOnly);

/** The two numbers of a "<label> A to B" chip. */
async function chipRange(page: Page, label: RegExp): Promise<[number, number]> {
  const text = await terms(page).locator(".gk-term", { hasText: label }).first().locator(".gk-term-text").innerText();
  const [, a, b] = text.match(/(-?[\d.]+) to (-?[\d.]+)/) ?? [];
  return [Number(a), Number(b)];
}

test("choosing a sweep fills the table, newest first, and the other views follow", async ({ page }) => {
  const { rows, newer } = await open(page);
  const options = await scenarios(page).getByLabel("Sweep", { exact: true }).locator("option").allInnerTexts();
  expect(options[1]).toContain(newer);
  await expect(page.getByText("Choose a sweep to see its scenarios.")).toBeVisible();
  await expect(tableRows(page)).toHaveCount(0);

  await chooseSweep(page, newer);
  await expect(tableRows(page)).toHaveCount(inFilter(rows).length);
  await expect(scenarios(page).locator(".gk-selection-count")).toContainText(`${inFilter(rows).length} of 24 scenarios`);

  await scenarios(page).getByLabel("Show inadmissible scenarios").check();
  await expect(tableRows(page)).toHaveCount(24);
  await expect(page.locator(".gk-line-ghost")).toHaveCount(24 - inFilter(rows).length);
});

test("a level filter narrows the table and both charts", async ({ page }) => {
  const { rows, newer } = await open(page);
  await chooseSweep(page, newer);
  const log = inFilter(rows).filter((row) => row.shear_model === "log_law");

  await scenarios(page).getByRole("group", { name: "Vertical profile (B)" }).getByLabel("power_law").uncheck();
  await expect(tableRows(page)).toHaveCount(log.length);
  await expect(terms(page)).toContainText("Vertical profile (B) log_law");
  await expect(page.locator(".gk-line-kept")).toHaveCount(log.length);
  await expect(histogram(page)).toHaveAccessibleName(new RegExp(`${log.length} kept by every brush`));

  await terms(page).getByRole("button", { name: /Clear the term/ }).click();
  await expect(tableRows(page)).toHaveCount(inFilter(rows).length);
});

test("a histogram brush filters the table and the parallel coordinates; Shift adds a range; Escape clears", async ({ page }) => {
  const { rows, newer } = await open(page);
  await chooseSweep(page, newer);
  const box = await histogram(page).boundingBox();
  if (!box) throw new Error("no histogram");
  const left = 40;
  const plot = box.width - 40 - 12;

  await drag(page, histogram(page), { x: left + plot * 0.3, y: 60 }, { x: left + plot * 0.6, y: 60 });
  await expect(terms(page)).toContainText("Distribution");
  const [lo, hi] = await chipRange(page, /Distribution/);
  const expected = inFilter(rows).filter((row) => row.long_term_mean_speed_mps >= lo && row.long_term_mean_speed_mps <= hi).length;
  expect(expected).toBeGreaterThan(0);
  expect(expected).toBeLessThan(inFilter(rows).length);
  await expect(tableRows(page)).toHaveCount(expected);
  await expect(page.locator(".gk-line-kept")).toHaveCount(expected);

  await drag(page, histogram(page), { x: left + plot * 0.85, y: 60 }, { x: left + plot * 0.98, y: 60 }, true);
  await expect(terms(page).locator(".gk-term-text", { hasText: /Long-term mean speed .* or / })).toBeVisible();
  await expect(async () => expect(await tableRows(page).count()).toBeGreaterThan(expected)).toPass();

  await histogram(page).focus();
  await page.keyboard.press("Escape");
  await expect(tableRows(page)).toHaveCount(inFilter(rows).length);
  await expect(page.getByText("Brush a chart or untick a level to filter.")).toBeVisible();
});

test("a parallel axis brush filters the histogram's highlight and the table", async ({ page }) => {
  const { rows, newer } = await open(page);
  await chooseSweep(page, newer);
  const box = await parallel(page).boundingBox();
  if (!box) throw new Error("no parallel coordinates");
  const step = (box.width - 56) / 9;
  const axisX = (index: number) => 28 + index * step;

  // The vertical-profile axis (third): log_law is its top level.
  await drag(page, parallel(page), { x: axisX(2), y: 112 }, { x: axisX(2), y: 130 });
  await expect(terms(page)).toContainText("Vertical profile (B) log_law");
  const log = inFilter(rows).filter((row) => row.shear_model === "log_law");
  await expect(tableRows(page)).toHaveCount(log.length);
  await expect(histogram(page)).toHaveAccessibleName(new RegExp(`${log.length} kept by every brush`));
  await expect(page.locator(".gk-hist-kept").first()).toBeAttached();

  // Uncertainty (ninth axis, numeric): brush the middle of its range.
  await drag(page, parallel(page), { x: axisX(8), y: 160 }, { x: axisX(8), y: 260 });
  const chip = terms(page).locator(".gk-term", { hasText: "Total uncertainty" });
  await expect(chip).toBeVisible();
  const [a, b] = await chipRange(page, /Total uncertainty/);
  const expected = log.filter((row) => row.total_uncertainty_pct >= a && row.total_uncertainty_pct <= b).length;
  await expect(tableRows(page)).toHaveCount(expected);
  await expect(page.locator(".gk-line-kept")).toHaveCount(expected);

  await parallel(page).focus();
  await page.keyboard.press("Escape");
  await expect(tableRows(page)).toHaveCount(inFilter(rows).length);
});

test("every brush has a keyboard way, and each term is removable on its own", async ({ page }) => {
  const { rows, newer } = await open(page);
  await chooseSweep(page, newer);

  const form = page.getByRole("form", { name: /Brush Long-term mean speed by value/ });
  await form.getByLabel("Minimum").fill("7");
  await form.getByLabel("Maximum").fill("8");
  await form.getByRole("button", { name: "Brush", exact: true }).click();
  const speedExpected = inFilter(rows).filter((row) => row.long_term_mean_speed_mps >= 7 && row.long_term_mean_speed_mps <= 8);
  await expect(tableRows(page)).toHaveCount(speedExpected.length);

  const axes = page.getByRole("group", { name: "Brush an axis by keyboard" });
  await axes.getByLabel("Axis").selectOption({ label: "Long-term reference (C)" });
  await axes.getByRole("group", { name: /Levels of/ }).getByRole("button", { name: "merra2" }).click();
  const both = speedExpected.filter((row) => row.reference_source === "merra2");
  await expect(tableRows(page)).toHaveCount(both.length);
  await expect(terms(page).locator(".gk-term")).toHaveCount(2);

  await terms(page).getByRole("button", { name: /Clear the term: Distribution/ }).click();
  await expect(terms(page).locator(".gk-term")).toHaveCount(1);
  await expect(tableRows(page)).toHaveCount(inFilter(rows).filter((row) => row.reference_source === "merra2").length);
  await terms(page).getByRole("button", { name: /Clear the term/ }).click();
  await expect(page.getByText("Brush a chart or untick a level to filter.")).toBeVisible();
});

test("two scenarios can be pinned; a third is refused until one is unpinned", async ({ page }) => {
  const { newer } = await open(page);
  await chooseSweep(page, newer);
  const pins = scenarios(page).getByRole("button", { name: /^Pin scenario/ });
  await pins.nth(0).click();
  await pins.nth(0).click();
  await expect(scenarios(page).getByText("Pinned 2 of 2: unpin one to pin another.")).toBeVisible();
  const others = scenarios(page).getByRole("button", { name: /^Pin scenario/ });
  await expect(others.first()).toBeDisabled();
  await scenarios(page).getByRole("button", { name: /^Unpin scenario/ }).first().click();
  await expect(scenarios(page).getByText("Pinned 1 of 2.")).toBeVisible();
  await expect(scenarios(page).getByRole("button", { name: /^Pin scenario/ }).first()).toBeEnabled();
});

test("the metric chooser re-draws the histogram, and sorting orders the table by it", async ({ page }) => {
  const { newer } = await open(page);
  await chooseSweep(page, newer);
  await scenarios(page).getByLabel("Metric").selectOption("total_uncertainty_pct");
  await expect(histogram(page)).toHaveAccessibleName(/Histogram of Total uncertainty/);
  await scenarios(page).getByRole("button", { name: /Total uncertainty/ }).click();
  const values = await tableRows(page).locator("td:nth-child(7)").allInnerTexts();
  const numbers = values.map(Number);
  expect(numbers).toEqual([...numbers].sort((a, b) => b - a));
});

test("axe finds nothing, and both themes render", async ({ page }, testInfo) => {
  const { newer } = await open(page);
  await chooseSweep(page, newer);
  const box = await histogram(page).boundingBox();
  if (!box) throw new Error("no histogram");
  await drag(page, histogram(page), { x: 40 + (box.width - 52) * 0.2, y: 60 }, { x: 40 + (box.width - 52) * 0.5, y: 60 });
  await expect(terms(page)).toContainText("Distribution");

  for (const theme of ["light", "dark"] as const) {
    if (theme === "dark") await page.getByRole("button", { name: "Dark theme" }).click();
    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations.map(
        (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
      ),
    ).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`interrogate-${theme}.png`) });
  }
});
