import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl } from "./fixtures";

// The profile (P2-17): mean speed by height for every record and for the shared selection,
// with the power-law exponent the server fits (compute_vertical_structure).

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

async function structure(page: import("@playwright/test").Page, sessionId: string, selection: string) {
  const response = await page.request.post(`/api/sessions/${sessionId}/operations/compute_vertical_structure`, {
    headers: { "X-GoKaatru-Session": sessionId },
    data: { speed_sensors: "", selection },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as { power_law_alpha: number; records_used: number; records_available: number };
}

test("the profile shows the server's exponent for every record and for the selection", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Profile ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const chart = page.getByRole("img", { name: /^Mean speed by height: 60 m .* 80 m .* 100 m/ });
  await expect(chart).toBeVisible();
  const every = await structure(page, opened.sessionId, "");
  const table = page.getByRole("table", { name: "Over records where every height is valid" });
  const everyRow = table.getByRole("row", { name: /Every record/ });
  await expect(everyRow).toContainText(every.power_law_alpha.toFixed(3));
  await expect(everyRow).toContainText(`${every.records_used} of ${every.records_available}`);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);

  await page.getByRole("group", { name: "Sectors" }).getByRole("button", { name: "W", exact: true }).click();
  const west = JSON.stringify({ kind: "sector", channel: "Dir_100m", from_deg: 255, to_deg: 285 });
  const selected = await structure(page, opened.sessionId, west);
  const selectedRow = table.getByRole("row", { name: /Selection/ });
  await expect(selectedRow).toContainText(selected.power_law_alpha.toFixed(3));
  await expect(selectedRow).toContainText(String(selected.records_used));
  await expect(chart).toHaveAttribute("aria-label", /; selection 60 m/);
  await page.screenshot({ path: testInfo.outputPath("profile.png") });
});
