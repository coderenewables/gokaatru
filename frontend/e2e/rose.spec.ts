import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl } from "./fixtures";

// The wind rose (P2-16, plan §3.3 "Wind rose"): clicking or dragging over sectors puts the
// rose's term in the crossfilter, which every view and the inspector then use.

const rose = (page: Page) => page.getByRole("img", { name: /^Wind rose of/ });
const terms = (page: Page) => page.getByRole("list", { name: "Selection terms" });
const sectors = (page: Page) => page.getByRole("group", { name: "Sectors" });

async function count(page: Page): Promise<number> {
  const text = await page.locator(".gk-selection-count strong").innerText();
  return Number(text);
}

async function clickBearing(page: Page, bearing: number, shift = false) {
  const box = await rose(page).boundingBox();
  if (!box) throw new Error("no rose");
  const radius = box.width * 0.3;
  const angle = (bearing * Math.PI) / 180;
  const x = box.x + box.width / 2 + radius * Math.sin(angle);
  const y = box.y + box.height / 2 - radius * Math.cos(angle);
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.click(x, y);
  if (shift) await page.keyboard.up("Shift");
}


// A chart that throws inside its library draws nothing and passes every other check.
let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

test("clicking sectors selects directions, Shift adds one, Escape clears", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Rose ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(rose(page)).toBeVisible();
  await expect(page.locator(".gk-rose-all").first()).toBeAttached();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);

  await clickBearing(page, 240);
  await expect(terms(page)).toContainText("Dir_100m 225° to 255°");
  await expect(sectors(page).getByRole("button", { name: "240°" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => count(page)).toBeGreaterThan(0);
  const one = await count(page);

  await clickBearing(page, 270, true);
  await expect(terms(page)).toContainText("Dir_100m 225° to 255° or Dir_100m 255° to 285°");
  await expect.poll(() => count(page)).toBeGreaterThan(one);
  await page.screenshot({ path: testInfo.outputPath("rose.png") });

  await rose(page).focus();
  await page.keyboard.press("Escape");
  await expect(page.getByText("Select on any chart.")).toBeVisible();
});

test("the sector buttons are the keyboard route, and north wraps through zero", async ({ page }) => {
  const opened = await campaignWithData(page, `Rose keys ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const north = sectors(page).getByRole("button", { name: "N", exact: true });
  await north.focus();
  await page.keyboard.press("Enter");
  await expect(terms(page)).toContainText("Dir_100m 345° to 15°");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Select on any chart.")).toBeVisible();
});
