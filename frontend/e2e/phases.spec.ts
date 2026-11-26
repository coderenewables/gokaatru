import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { newCampaign, pageErrors } from "./fixtures";

// The phases of the work in one shell (P3-10a, decisions/0015): each phase docks its own panels,
// the address names the phase, and each phase keeps its own arrangement.

const PHASE_TABS: Record<string, string[]> = {
  Prepare: ["Data", "Reanalysis", "Timeline", "Scatter", "Wind rose", "Profile", "Inspector", "Cleaning rules", "Sensor overview"],
  Model: ["Methods", "Pipeline", "Step"],
  Run: ["Sweep design", "Run"],
  Interrogate: ["Scenarios", "Distribution", "Parallel coordinates", "Sensitivity", "Gates", "Side by side"],
};

function tab(page: Page, title: string): Locator {
  return page.locator(".dv-tab", { hasText: new RegExp(`^${title}$`) });
}

function phase(page: Page, name: string): Locator {
  return page.getByRole("navigation", { name: "Phases" }).getByRole("button", { name, exact: true });
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
}

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

test("each phase docks its own panels, named in the address, and passes axe", async ({ page }, testInfo) => {
  const { projectId, sessionId } = await newCampaign(page, `Phases ${Date.now()}`);
  await page.goto(`/?project=${projectId}&campaign=${sessionId}`);
  await expect(phase(page, "Prepare")).toHaveAttribute("aria-current", "page");

  for (const [name, tabs] of Object.entries(PHASE_TABS)) {
    await phase(page, name).click();
    await expect(phase(page, name)).toHaveAttribute("aria-current", "page");
    for (const title of tabs) await expect(tab(page, title)).toBeVisible();
    if (name !== "Prepare") {
      await expect(page).toHaveURL(new RegExp(`phase=${name.toLowerCase()}`));
      await expect(tab(page, "Timeline")).toHaveCount(0);
    }
    await expectNoAxeViolations(page);
    await page.screenshot({ path: testInfo.outputPath(`phase-${name.toLowerCase()}.png`) });
  }

  await page.reload();
  await expect(phase(page, "Interrogate")).toHaveAttribute("aria-current", "page");
  await expect(tab(page, "Distribution")).toBeVisible();
});

test("each phase keeps its own arrangement", async ({ page }) => {
  const { projectId, sessionId } = await newCampaign(page, `Arrangement ${Date.now()}`);
  await page.goto(`/?project=${projectId}&campaign=${sessionId}&phase=run`);
  await expect(tab(page, "Sweep design")).toBeVisible();
  await page.getByRole("button", { name: "Close Run" }).click();
  await expect(tab(page, "Run")).toHaveCount(0);

  await phase(page, "Prepare").click();
  await expect(tab(page, "Timeline")).toBeVisible();
  await expect(tab(page, "Scatter")).toBeVisible();

  await phase(page, "Run").click();
  await expect(tab(page, "Sweep design")).toBeVisible();
  await expect(tab(page, "Run")).toHaveCount(0);
  await page.getByRole("button", { name: "Reset layout" }).click();
  await expect(tab(page, "Run")).toBeVisible();
});

test("the command palette goes to another phase", async ({ page }) => {
  const { projectId, sessionId } = await newCampaign(page, `Palette ${Date.now()}`);
  await page.goto(`/?project=${projectId}&campaign=${sessionId}`);
  await expect(tab(page, "Timeline")).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog", { name: "Commands" })).toBeVisible();
  await page.keyboard.type("go to model");
  await page.keyboard.press("Enter");
  await expect(phase(page, "Model")).toHaveAttribute("aria-current", "page");
  await expect(tab(page, "Pipeline")).toBeVisible();
});
