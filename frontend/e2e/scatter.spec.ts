import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Request } from "@playwright/test";

import { campaignWithData, FROZEN_RECORDS, pageErrors, workbenchUrl } from "./fixtures";

// The scatter panel (P2-15, plan §3.3 "Scatter"): lasso the points that disagree and every
// view shares the same selection. Headless Chromium draws WebGL in software, so these assert
// behaviour, not speed.

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

const overlay = (page: Page) => page.getByTestId("scatter-overlay");

/** A lasso over the plot, each vertex as a fraction of the plot's width and height from its
 * top-left corner. */
async function lasso(page: Page, fractions: [number, number][], shift = false) {
  const box = await overlay(page).boundingBox();
  if (!box) throw new Error("the plot is not drawn");
  const at = ([fx, fy]: [number, number]) => ({ x: box.x + fx * box.width, y: box.y + fy * box.height });
  if (shift) await page.keyboard.down("Shift");
  const first = at(fractions[0]);
  await page.mouse.move(first.x, first.y);
  await page.mouse.down();
  for (const vertex of [...fractions.slice(1), fractions[0]]) {
    const point = at(vertex);
    await page.mouse.move(point.x, point.y, { steps: 6 });
  }
  await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
}

/** The corners, as plot fractions, of the strip between two data heights of the y axis. */
async function strip(page: Page, from: number, to: number): Promise<[number, number][]> {
  const hi = Number(await overlay(page).getAttribute("data-y-hi"));
  const top = 1 - to / hi;
  const bottom = 1 - from / hi;
  // Wider than the plot, so no record on its edge falls outside the lasso.
  // It starts inside the plot, where a drag begins.
  return [[0.5, top], [1.03, top], [1.03, bottom], [-0.03, bottom], [-0.03, top]];
}

const chip = (page: Page) => page.getByRole("list", { name: "Selection terms" }).getByRole("listitem").filter({ hasText: "Scatter" });
const count = (page: Page) => page.locator(".gk-selection-count strong");

function highlightedPairs(page: Page): Promise<Request> {
  return page.waitForRequest((request) => {
    if (!request.url().endsWith("/pairs") || request.method() !== "POST") return false;
    return JSON.parse(request.postData() ?? "{}").highlight !== "";
  });
}

async function open(page: Page) {
  const opened = await campaignWithData(page, `Scatter ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.getByLabel("X axis")).toHaveValue("Spd_80m");
  await expect(page.getByText(/records with both channels/).first()).toBeVisible();
  await expect(overlay(page)).toBeVisible();
  return opened;
}


// A chart that throws inside its library draws nothing and passes every other check.
let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

test("the scatter draws the two highest speeds and passes axe", async ({ page }) => {
  await open(page);
  await expect(page.getByLabel("X axis")).toHaveValue("Spd_80m");
  await expect(page.getByLabel("Y axis")).toHaveValue("Spd_100m");
  await expect(page.locator(".gk-scatter-caption")).toHaveText(/^\d+ of \d+ records with both channels$/);
  await expect(page.getByRole("img", { name: /Scatter of Spd_100m against Spd_80m/ })).toBeVisible();
  await expectNoAxeViolations(page);
});

test("a lasso around the frozen cup selects its records, counted by the server", async ({ page }) => {
  const opened = await open(page);
  const request = highlightedPairs(page);
  await lasso(page, await strip(page, -0.4, 0.5));
  const selection = JSON.parse((await request).postData() ?? "{}").highlight as string;
  const polygon = JSON.parse(selection);
  expect(polygon.kind).toBe("polygon");
  expect(polygon.vertices.length).toBeLessThanOrEqual(200);
  expect(polygon.x_channel).toBe("Spd_80m");
  expect(polygon.y_channel).toBe("Spd_100m");

  await expect(chip(page)).toBeVisible();
  await expect(count(page)).toHaveText(String(FROZEN_RECORDS));
  const summary = await page.request.post(`/api/sessions/${opened.sessionId}/operations/summarise_channels`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: { channels: "Spd_100m", selection },
  });
  expect(summary.ok()).toBeTruthy();
  expect((await summary.json()).selection.records).toBe(FROZEN_RECORDS);
  await expect(page.locator(".gk-scatter-caption")).toContainText(`${FROZEN_RECORDS} highlighted`);
});

test("Escape clears the term and Shift adds a second lasso to the same chip", async ({ page }) => {
  await open(page);
  await lasso(page, await strip(page, -0.4, 0.5));
  await expect(chip(page)).toBeVisible();
  await page.getByRole("img", { name: /Scatter of/ }).focus();
  await page.keyboard.press("Escape");
  await expect(chip(page)).toHaveCount(0);
  await expect(page.locator(".gk-scatter-caption")).not.toContainText("highlighted");

  await lasso(page, await strip(page, -0.4, 0.5));
  await expect(chip(page)).toHaveCount(1);
  await lasso(page, [[0.3, 0.3], [0.6, 0.3], [0.6, 0.6], [0.3, 0.6]], true);
  await expect(chip(page)).toHaveCount(1);
  await expect(chip(page)).toContainText(/lasso of \d+ points.*lasso of \d+ points/);
  await expect(page.locator(".gk-scatter-lasso")).toHaveCount(2);

  // A click without a drag clears it too.
  const box = (await overlay(page).boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.1);
  await expect(chip(page)).toHaveCount(0);
});

test("changing the x axis redraws with the new channel", async ({ page }) => {
  await open(page);
  await page.getByLabel("X axis").selectOption("Spd_60m");
  await expect(page.getByRole("img", { name: /Scatter of Spd_100m against Spd_60m/ })).toBeVisible();
  await expect(page.locator(".gk-scatter-caption")).toHaveText(/^\d+ of \d+ records with both channels$/);
});

for (const theme of ["light", "dark"] as const) {
  test(`the scatter with a selection in the ${theme} theme`, async ({ page }, testInfo) => {
    await open(page);
    if (theme === "dark") {
      await page.getByRole("button", { name: "Dark theme" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    }
    await lasso(page, await strip(page, -0.4, 0.5));
    await expect(chip(page)).toBeVisible();
    await expect(page.locator(".gk-scatter-caption")).toContainText("highlighted");
    await expectNoAxeViolations(page);
    await page.screenshot({ path: testInfo.outputPath(`scatter-${theme}.png`) });
  });
}
