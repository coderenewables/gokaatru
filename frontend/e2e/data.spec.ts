import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { campaignWithData, newCampaign, workbenchUrl } from "./fixtures";

// The data tree (P2-12): the campaign's instruments by height with their statistic channels,
// matching the inventory the server lists, and the flags the cleaning log holds.

test("the data tree lists every instrument by height, its statistics and the flags", async ({ page }, testInfo) => {
  const opened = await campaignWithData(page, `Tree ${Date.now()}`);
  await page.goto(workbenchUrl(opened));

  const listed = await page.request.post(`/api/sessions/${opened.sessionId}/operations/list_instruments`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: {},
  });
  const inventory = (await listed.json()) as {
    heights: number[];
    instruments: Array<{ name: string; height_m: number; statistics: string[] }>;
  };
  expect(inventory.heights).toEqual([100, 80, 60]);

  for (const height of inventory.heights) {
    const group = page.getByRole("region", { name: `${height} m` });
    await expect(group).toBeVisible();
    const expected = inventory.instruments.filter((instrument) => instrument.height_m === height);
    for (const instrument of expected) {
      await expect(group.getByText(instrument.name, { exact: true }).first()).toBeVisible();
      if (instrument.statistics.length > 0) {
        const statistics = group.getByRole("list", { name: `Statistics of ${instrument.name}` });
        for (const column of instrument.statistics) await expect(statistics.getByText(column, { exact: true })).toBeVisible();
      }
    }
  }
  const top = page.getByRole("region", { name: "100 m" });
  await expect(top.getByText("speed", { exact: false }).first()).toBeVisible();
  await expect(top.getByRole("list", { name: "Statistics of Spd_100m" })).toContainText("Spd_100m_sd");
  await expect(page.getByRole("region", { name: "Flags" })).toContainText("No records flagged.");
  await expect(page.getByRole("region", { name: "Reanalysis" })).toContainText("None loaded.");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("data-tree.png") });

  const flagged = await page.request.post(`/api/sessions/${opened.sessionId}/operations/apply_cleaning_rule`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: {
      rule_type: "custom_period_exclude",
      sensor: "Spd_100m",
      params: "{}",
      start_date: "2023-03-14 21:20",
      end_date: "2023-03-15 05:10",
    },
  });
  expect(flagged.ok(), await flagged.text()).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("region", { name: "Flags" })).toContainText("Spd_100m 48 records, excluded period (rule 1)");
});

test("an empty campaign says to load its files", async ({ page }) => {
  const opened = await newCampaign(page, `Empty tree ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.getByText("No data yet. Load the campaign's files to see its channels here.")).toBeVisible();
});
