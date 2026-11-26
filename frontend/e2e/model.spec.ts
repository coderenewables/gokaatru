import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl } from "./fixtures";

// The Model (plan §3.3 "Model", decisions/0015.1-0015.5): methods dragged from the palette,
// wired by what they read and write, parameters in generated forms, each step's status, run
// what is stale one step at a time, and named pipelines.

const PAIR = JSON.stringify({ "80": "Spd_80m", "100": "Spd_100m" });

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

function stepsInOrder(page: Page): Locator {
  return page.getByRole("list", { name: "Steps in order" });
}

function badge(page: Page, id: string): Locator {
  return stepsInOrder(page).getByRole("listitem").filter({ has: page.getByRole("button", { name: id, exact: true }) }).locator(".gk-step-badge");
}

async function add(page: Page, method: string) {
  await page.getByRole("button", { name: `Add ${method} to the pipeline` }).click();
}

async function selectStep(page: Page, id: string) {
  await stepsInOrder(page).getByRole("button", { name: id, exact: true }).click();
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
}

test("a pipeline is built from the palette, ordered by its data, run step by step, and its staleness shown", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Model ${Date.now()}`);
  await page.goto(`${workbenchUrl(opened)}&phase=model`);
  await expect(page.getByRole("heading", { name: "Shear" })).toBeVisible();

  // Added out of order: the server puts the shear series first because the others read it.
  await add(page, "extrapolate to hub height");
  await add(page, "build shear table");
  await add(page, "calculate shear timeseries");
  await expect(stepsInOrder(page).getByRole("button")).toHaveText(["shear_timeseries", "shear_table", "extrapolate_to_hub_height"]);

  await selectStep(page, "shear_timeseries");
  await page.getByLabel(/height sensors/).fill(PAIR);
  await selectStep(page, "extrapolate_to_hub_height");
  await page.getByLabel(/hub height \(m\)/).fill("120");
  await expect(badge(page, "extrapolate_to_hub_height")).toHaveText("not run");

  await page.getByRole("button", { name: "Run stale (3)" }).click();
  await expect(page.getByRole("button", { name: "Nothing to run" })).toBeVisible({ timeout: 60_000 });
  for (const id of ["shear_timeseries", "shear_table", "extrapolate_to_hub_height"]) await expect(badge(page, id)).toHaveText("current");
  await expect(page.getByRole("contentinfo", { name: "Status" })).not.toContainText("stale");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("model-light.png") });

  // Another aggregation: the table's result is not this step's any more, and the hub series waits on it.
  await selectStep(page, "shear_table");
  await page.getByLabel(/^aggregation/).fill("median");
  await expect(badge(page, "shear_table")).toHaveText("changed");
  await expect(badge(page, "extrapolate_to_hub_height")).toHaveText("waits");
  await expect(page.getByRole("button", { name: "Run stale (2)" })).toBeVisible();

  await page.getByRole("button", { name: "Dark theme" }).click();
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("model-dark.png") });
});

test("a refused step says why and stops the run there", async ({ page }) => {
  const opened = await campaignWithData(page, `Refused ${Date.now()}`);
  await page.goto(`${workbenchUrl(opened)}&phase=model`);
  await add(page, "calculate shear timeseries");
  await add(page, "build shear table");
  await selectStep(page, "shear_timeseries");
  await page.getByLabel(/height sensors/).fill(JSON.stringify({ "80": "Spd_80m", "100": "Nope" }));
  await page.getByRole("button", { name: "Run stale (2)" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Refused" })).toBeVisible({ timeout: 60_000 });
  await expect(badge(page, "shear_table")).toHaveText("not run");
});

test("two steps building one result are refused, naming both", async ({ page }) => {
  const opened = await campaignWithData(page, `Conflict ${Date.now()}`);
  await page.goto(`${workbenchUrl(opened)}&phase=model`);
  await add(page, "build shear table");
  await add(page, "build aggr momm shear table");
  await expect(page.getByRole("alert").filter({ hasText: "One step produces each result" })).toContainText("shear_table by");
});

test("a method dragged onto the pipeline is added, and a named pipeline reopens", async ({ page }) => {
  const opened = await campaignWithData(page, `Named ${Date.now()}`);
  await page.goto(`${workbenchUrl(opened)}&phase=model`);
  const method = page.locator(".gk-method-name", { hasText: /^calculate shear timeseries$/ });
  const target = page.locator(".gk-pipeline");
  const from = await method.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) throw new Error("nothing to drag");
  await page.mouse.move(from.x + 10, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + 30, from.y + 20, { steps: 4 });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 20 });
  await page.mouse.up();
  await expect(stepsInOrder(page).getByRole("button")).toHaveText(["shear_timeseries"]);

  await page.getByLabel("Name").fill("chosen");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved as chosen.")).toBeVisible();

  // The pipeline being edited is this browser's; the saved one is the campaign's.
  await page.reload();
  await expect(stepsInOrder(page).getByRole("button")).toHaveText(["shear_timeseries"]);
  await selectStep(page, "shear_timeseries");
  await page.getByRole("button", { name: "Remove from the pipeline" }).click();
  await expect(stepsInOrder(page).getByRole("button")).toHaveCount(0);
  await page.getByLabel("Open").selectOption("chosen");
  await expect(stepsInOrder(page).getByRole("button")).toHaveText(["shear_timeseries"]);
});
