import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { campaignWithData, pageErrors, workbenchUrl } from "./fixtures";
import { stubSweeps } from "./sweepRows";

// A sweep scenario loaded into Model, and a pipeline swept in Run (P3-11, decisions/0015.1).
// Browser tests cannot run a sweep (no reanalysis without the network), so the sweep and the
// scenario's steps are faked; that running a loaded scenario reproduces its row is held on the
// server, row by row (tests/test_scenario_reproduction.py). "Sweep around this" is the real
// operation on the campaign.

const PAIR = JSON.stringify({ "80": "Spd_80m", "100": "Spd_100m" });
const STEPS = [
  { id: "shear_series", operation: "calculate_shear_timeseries", parameters: { height_sensors: PAIR } },
  { id: "shear_table", operation: "build_shear_table", parameters: { aggregation: "mean" } },
  {
    id: "hub",
    operation: "extrapolate_to_hub_height",
    parameters: { hub_height_m: 120, shear_model: "power_law", reference_columns: ["Spd_80m", "Spd_100m"], extrapolate_reanalysis: false },
  },
  {
    id: "correction",
    operation: "run_ltc_variance_ratio",
    parameters: { short_col: "Spd_120m_hub", long_col: "Spd_100m", reference_source: "era5" },
  },
  {
    id: "uncertainty",
    operation: "calculate_scenario_uncertainty",
    parameters: { algorithm: "variance_ratio", shear_model: "power_law_mean", reference_heights: [80, 100], hub_height_m: 120, shear_source: "fitted" },
  },
];

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

async function fakeScenario(page: Page, prefixMatches: boolean) {
  await page.route(/\/operations\/pipeline_from_scenario$/, async (route: Route) => {
    const body = route.request().postDataJSON() as { sweep_id: string; config_hash: string };
    await route.fulfill({
      json: {
        sweep_id: body.sweep_id,
        config_hash: body.config_hash,
        scenario: {
          shear_fit_policy: "nearest_2", reference_policy: "nearest_2", shear_model: "power_law_mean",
          reference_source: "era5", ltc_algorithm: "variance_ratio", hub_height_m: 120, analyst_shear_alpha: null,
        },
        steps: STEPS,
        prefix_matches: prefixMatches,
        ...(prefixMatches ? {} : { prefix_note: "The campaign's data, cleaning, reanalysis or engine has changed since this sweep ran: the steps run on today's session and will not reproduce the scenario's row." }),
      },
    });
  });
}

async function loadFirstScenario(page: Page, prefixMatches = true) {
  const stub = await stubSweeps(page);
  await fakeScenario(page, prefixMatches);
  const opened = await campaignWithData(page, `Scenario ${Date.now()}`);
  await page.goto(`${workbenchUrl(opened)}&phase=interrogate`);
  const scenarios = page.locator(".gk-interrogate", { has: page.getByLabel("Sweep", { exact: true }) });
  await scenarios.getByLabel("Sweep", { exact: true }).selectOption(stub.newer);
  const row = stub.rows.find((candidate) => candidate.status === "ok");
  if (!row) throw new Error("no completed row to load");
  await page.getByRole("button", { name: `Load scenario ${row.config_hash.slice(0, 8)} into Model` }).click();
  return row;
}

test("a scenario loads into Model as its steps, in the order they run", async ({ page }) => {
  const row = await loadFirstScenario(page);
  const phases = page.getByRole("navigation", { name: "Phases" });
  await expect(phases.getByRole("button", { name: "Model", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page).toHaveURL(/phase=model/);
  await expect(page.getByRole("list", { name: "Steps in order" }).getByRole("button")).toHaveText(STEPS.map((step) => step.id));
  await expect(page.getByRole("status").filter({ hasText: "Loaded from sweep" })).toContainText(row.config_hash.slice(0, 8));
  await expect(page.getByRole("status").filter({ hasText: "Loaded from sweep" })).toContainText("reproduces that scenario's row");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
});

test("a scenario from a sweep the campaign has moved on from says so", async ({ page }) => {
  await loadFirstScenario(page, false);
  await expect(page.getByRole("status").filter({ hasText: "Loaded from sweep" })).toContainText("will not reproduce");
});

test("sweeping around a pipeline fills the Run design with its own choices", async ({ page }) => {
  await loadFirstScenario(page);
  await page.getByRole("button", { name: "Sweep around this" }).click();
  const phases = page.getByRole("navigation", { name: "Phases" });
  await expect(phases.getByRole("button", { name: "Run", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("checkbox", { name: /power law mean/i }).first()).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /variance ratio/i }).first()).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /log law/i }).first()).not.toBeChecked();
});
