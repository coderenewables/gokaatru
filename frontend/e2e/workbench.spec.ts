import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { campaignWithData, newCampaign, pageErrors, workbenchUrl } from "./fixtures";

// The workbench shell at /workbench/ (P2-9, decisions/0006, 0012, 0014.9): a campaign opens
// the docked panels, the arrangement persists, both themes render, and axe finds nothing.

const PANELS = ["Data", "Reanalysis", "Timeline", "Scatter", "Wind rose", "Profile", "Inspector"];

function tab(page: Page, title: string): Locator {
  return page.locator(".dv-tab", { hasText: title });
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

async function dragTo(page: Page, from: Locator, target: Locator) {
  const source = await from.boundingBox();
  const box = await target.boundingBox();
  if (!source || !box) throw new Error("nothing to drag");
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await page.mouse.move(source.x + source.width / 2 + 8, source.y + source.height / 2 + 8, { steps: 4 });
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 20 });
  await page.mouse.move(box.x + box.width / 2 + 1, box.y + box.height / 2 + 1, { steps: 2 });
  await page.mouse.up();
}

// Each test runs in a fresh browser context, so it starts with no stored layout or theme.


// A chart that throws inside its library draws nothing and passes every other check.
let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

test("the start screen lists a project's campaigns and opens the shell on one", async ({ page }) => {
  const name = `Start ${Date.now()}`;
  const { projectId, sessionId } = await newCampaign(page, name);
  await page.goto("/workbench/");
  const project = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name }) });
  await expect(project).toBeVisible();
  await expectNoAxeViolations(page);

  await project.getByRole("link", { name: "Mast M1" }).click();
  await expect(page).toHaveURL(new RegExp(`project=${projectId}&campaign=${sessionId}`));
  await expect(page.getByRole("navigation", { name: "Where you are" })).toContainText(`${name}›Mast M1`);
});

test("the shell docks every Prepare panel, persists the arrangement and passes axe", async ({ page }, testInfo) => {
  const { projectId, sessionId } = await newCampaign(page, `Shell ${Date.now()}`);
  await page.goto(`/workbench/?project=${projectId}&campaign=${sessionId}`);
  for (const title of PANELS) await expect(tab(page, title)).toBeVisible();
  await expect(page.getByRole("contentinfo", { name: "Status" })).toContainText("No records loaded");
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("workbench-light.png") });

  // Closing a panel from its group's own control, outside the tab, and reloading.
  await page.getByRole("button", { name: "Close Scatter" }).click();
  await expect(tab(page, "Scatter")).toHaveCount(0);
  await page.reload();
  await expect(tab(page, "Timeline")).toBeVisible();
  await expect(tab(page, "Scatter")).toHaveCount(0);

  // Dragging the profile onto the timeline makes it a tab of the timeline's group, kept on reload.
  await dragTo(page, tab(page, "Profile"), page.locator(".dv-groupview", { has: tab(page, "Timeline") }).locator(".dv-content-container"));
  const timelineGroup = page.locator(".dv-groupview", { has: tab(page, "Timeline") });
  await expect(timelineGroup.locator(".dv-tab", { hasText: "Profile" })).toBeVisible();
  await page.reload();
  await expect(page.locator(".dv-groupview", { has: tab(page, "Timeline") }).locator(".dv-tab", { hasText: "Profile" })).toBeVisible();

  await page.getByRole("button", { name: "Reset layout" }).click();
  for (const title of PANELS) await expect(tab(page, title)).toBeVisible();
});

test("a campaign with records shows them in the status bar and the inspector", async ({ page }) => {
  const opened = await campaignWithData(page, `Data ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const status = page.getByRole("contentinfo", { name: "Status" });
  await expect(status).toContainText("Records loaded");
  await expect(status).toContainText("Data model loaded");
  const means = page.getByRole("table", { name: /Mean, selection against every record/ });
  for (const channel of ["Spd_100m", "Spd_80m", "Spd_60m"]) {
    await expect(means.getByRole("rowheader", { name: channel })).toBeVisible();
  }
  await expect(means.getByRole("row", { name: /Spd_80m/ }).getByRole("cell").last()).not.toHaveText("—");
  await expectNoAxeViolations(page);
});

test("the dark theme applies, persists and passes axe", async ({ page }, testInfo) => {
  const { projectId, sessionId } = await newCampaign(page, `Theme ${Date.now()}`);
  await page.goto(`/workbench/?project=${projectId}&campaign=${sessionId}`);
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(15, 18, 23)");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(tab(page, "Timeline")).toBeVisible();
  await expectNoAxeViolations(page);
  await page.screenshot({ path: testInfo.outputPath("workbench-dark.png") });
});
