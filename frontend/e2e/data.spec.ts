import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { campaignWithData, newCampaign, pageErrors, workbenchUrl } from "./fixtures";

// The data tree (P2-12): the campaign's instruments by height with their statistic channels,
// matching the inventory the server lists, and the flags the cleaning log holds.


// A chart that throws inside its library draws nothing and passes every other check.
let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

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

test("a channel dragged from the data tree onto the timeline joins it", async ({ page }) => {
  // Plan §3.3 "Any chart": drag a channel from the data tree onto a chart.
  const opened = await campaignWithData(page, `Drag ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const legend = page.getByRole("list", { name: "Timeline channels" });
  await expect(legend.getByRole("listitem")).toHaveCount(3);

  const chip = page.getByRole("region", { name: "100 m" }).getByRole("button", { name: /^Tmp_100m/ });
  const plot = page.getByRole("img", { name: /^Timeline of/ });
  const from = await chip.boundingBox();
  const to = await plot.boundingBox();
  if (!from || !to) throw new Error("nothing to drag");
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2 + 10, { steps: 5 });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 20 });
  await page.mouse.up();

  await expect(legend.getByRole("listitem")).toHaveCount(4);
  await expect(legend).toContainText("Tmp_100m");
  await expect(plot).toHaveAttribute("aria-label", /Tmp_100m/);
});

test("a sensor is removed from the analysis after a preview, and Undo puts it back", async ({ page }) => {
  const opened = await campaignWithData(page, `Remove ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.getByRole("region", { name: "60 m" })).toBeVisible();

  const removal = page.locator("details.gk-removal");
  await removal.getByText("Remove sensors from the analysis").click();
  const preview = removal.getByRole("button", { name: "Preview" });
  await expect(preview).toBeDisabled();
  await removal.getByRole("checkbox", { name: "Spd_60m" }).check();
  await preview.click();
  await expect(removal.getByRole("status")).toHaveText(
    "Would remove Spd_60m, taking out the columns Spd_60m; 4 sensors remain.",
  );
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);

  await removal.getByRole("button", { name: "Remove 1 sensor" }).click();
  await expect(page.getByRole("region", { name: "60 m" })).toHaveCount(0);
  const log = await page.request.post(`/api/sessions/${opened.sessionId}/operations/get_operation_log`, {
    headers: { "X-GoKaatru-Session": opened.sessionId },
    data: {},
  });
  const entries = ((await log.json()) as { entries: Array<{ operation: string; actor: string }> }).entries;
  // Through the generated route, as the user; the reads the panels make afterwards follow it.
  expect(entries.filter((entry) => entry.operation === "remove_sensors")).toEqual([
    expect.objectContaining({ operation: "remove_sensors", actor: "user" }),
  ]);

  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByRole("region", { name: "60 m" })).toBeVisible();
});

test("an empty campaign imports a BrightHub location, with what BrightHub applies first chosen and said", async ({ page }) => {
  // BrightHub is faked in the browser, as in reanalysis.spec.ts; the server's import is held by
  // pytest against a fake of the BrightHub API.
  let signedIn = false;
  const imports: Array<Record<string, unknown>> = [];
  const json = (body: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/operations/brighthub_status", (route) => route.fulfill(json({ authenticated: signedIn, has_token: signedIn })));
  await page.route("**/operations/brighthub_login", (route) => {
    signedIn = true;
    return route.fulfill(json({ status: "ok", authenticated: true }));
  });
  await page.route("**/operations/brighthub_list_locations", (route) =>
    route.fulfill(
      json({
        count: 2,
        locations: [
          { uuid: "loc-a", name: "North ridge mast", latitude_ddeg: 55.25, longitude_ddeg: 7.75, measurement_station_type_id: "mast" },
          { uuid: "loc-b", name: "South lidar", latitude_ddeg: 55.1, longitude_ddeg: 7.6, measurement_station_type_id: "lidar" },
        ],
      }),
    ),
  );
  await page.route("**/operations/brighthub_import_location", (route) => {
    imports.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill(
      json({
        status: "ok", uuid: "loc-a", timeseries_rows: 52560, timeseries_columns: [], timeseries_start: "2023-01-01 00:00",
        timeseries_end: "2023-12-31 23:50", datamodel_heights: [100, 80], project_name: "North ridge mast", measurement_type: "mast",
        upstream_processing: {}, upstream_processing_note: "Applied by BrightHub before import.",
      }),
    );
  });

  const opened = await newCampaign(page, `BrightHub ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  const panel = page.locator("details.gk-bh-import");
  await panel.getByText("Or import a BrightHub location").click();
  await panel.getByLabel("Client ID").fill("id");
  await panel.getByLabel("Client secret").fill("secret");
  await panel.getByRole("button", { name: "Sign in" }).click();
  await panel.getByLabel("Location").selectOption({ label: "North ridge mast" });
  await expect(panel.getByRole("checkbox", { name: "BrightHub's cleaning log" })).toBeChecked();
  await panel.getByRole("checkbox", { name: "Calibration" }).check();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await panel.getByRole("button", { name: "Import" }).click();
  await expect(panel.getByRole("status")).toContainText("Imported 52560 records from 2023-01-01 00:00 to 2023-12-31 23:50.");
  expect(imports).toEqual([
    {
      uuid: "loc-a", name: "North ridge mast", latitude_ddeg: 55.25, longitude_ddeg: 7.75, apply_cleaning_log: true,
      apply_cleaning_rules: false, apply_calibration: true, apply_deadband_offset: false, apply_orientation_offset: false,
    },
  ]);
});

test("an empty campaign says to load its files", async ({ page }) => {
  const opened = await newCampaign(page, `Empty tree ${Date.now()}`);
  await page.goto(workbenchUrl(opened));
  await expect(page.getByText("No data yet. Load the campaign's files to see its channels here.")).toBeVisible();
});
