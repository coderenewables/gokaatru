import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { newCampaign, pageErrors } from "./fixtures";
import { stubSweeps, sweepRows } from "./sweepRows";

// Interrogate's sensitivity, gates and side-by-side panels (P3-15, decisions/0015.7, 0015.8).
// The decomposition is the server's, asked over the scenarios the brushes keep; the sweep and
// its answers are faked, as no sweep can run in a browser test.

const NOT_SWEPT =
  "Not swept: wind direction, temperature and air density. Every scenario in this sweep uses the same ones, so the spread covers the wind-speed chain only: sensor choice, shear, reference source and long-term method.";

const json = (route: Route, body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const tab = (page: Page, title: string) => page.locator(".dv-tab", { hasText: new RegExp(`^${title}$`) });

let thrown: string[] = [];
test.beforeEach(({ page }) => {
  thrown = pageErrors(page);
});
test.afterEach(() => {
  expect(thrown).toEqual([]);
});

const THRESHOLDS = { concurrent_months_warn: 12, concurrent_months_fail: 9 };

async function open(page: Page, extra: Record<string, unknown>[] = []) {
  const stub = await stubSweeps(page);
  const rows = [
    ...sweepRows().map((row) => ({
      ...row,
      gate_concurrent_period: row.admissible ? "pass" : "fail",
      gate_concurrent_period_value: row.admissible ? 12.5 : 7.25,
    })),
    ...extra,
  ] as ReturnType<typeof sweepRows>;
  await page.route(/\/api\/sessions\/[^/]+\/sweep\/sweep-[^/]+$/, (route) =>
    json(route, { manifest: { sweep_id: stub.newer, thresholds: THRESHOLDS }, results: rows }),
  );
  const spreadRequests: string[][] = [];
  await page.route(/\/sweep\/[^/]+\/spread$/, (route) => {
    const body = route.request().postDataJSON() as { config_hashes: string[] };
    spreadRequests.push(body.config_hashes);
    return json(route, {
      sweep_id: stub.newer,
      metric: "long_term_mean_speed_mps",
      scenarios_analysed: body.config_hashes.length,
      contributions: [
        { axis: "shear_model", levels: 2, share: 0.62, swing: 0.8, level_means: [], duplicate_levels: {} },
        { axis: "reference_source", levels: 2, share: 0.23, swing: 0.35, level_means: [], duplicate_levels: {} },
      ],
      single_level_axes: ["reference_policy"],
      basis: "first_order_between_group_variance",
      basis_note: "A first-order decomposition.",
      single_level_note: "One level is not a finding that the choice does not matter.",
      duplicate_note: "",
      spread: { count: body.config_hashes.length, min: 6.5, max: 8.1, mean: 7.2, std: 0.4, range: 1.6 },
      uncertainty_substitution: { available: false, reason: "Fewer than three levels on every axis." },
      not_swept: ["wind_direction", "temperature", "air_density"],
      not_swept_statement: NOT_SWEPT,
      not_swept_recorded_in_manifest: true,
    });
  });
  await page.route(/\/operations\/get_sweep_summary$/, (route) =>
    json(route, {
      sweep_id: stub.newer, fixed_prefix_hash: "prefix000000abcd", engine_version: "2026.11.3",
      scenarios_total: rows.length, scenarios_admissible: rows.filter((row) => row.admissible).length, duplicates_skipped: 0,
      axes: { shear_model: { levels_designed: ["log_law_mean", "power_law_mean"], levels_admissible: ["log_law_mean", "power_law_mean"], duplicate_levels: {}, collapsed_to_one_level: false } },
      gate_failures: { concurrent_period: rows.filter((row) => !row.admissible).length },
      note: "Collapsed means not varied.", duplicate_note: "Same sensors.",
      not_swept: [], not_swept_statement: NOT_SWEPT, not_swept_recorded_in_manifest: true,
    }),
  );
  await page.route(/\/scenarios\/[^/]+\/runconfig$/, (route) => {
    const hash = route.request().url().split("/scenarios/")[1].split("/")[0];
    const row = rows.find((candidate) => candidate.config_hash === hash);
    return json(route, { hub_height_m: 120, scenario: { config_hash: hash, shear_model: row?.shear_model, ltc_algorithm: row?.ltc_algorithm } });
  });
  const campaign = await newCampaign(page, `Panels ${Date.now()}`);
  await page.goto(`/?project=${campaign.projectId}&campaign=${campaign.sessionId}&phase=interrogate`);
  const scenarios = page.locator(".gk-interrogate", { has: page.getByLabel("Sweep", { exact: true }) });
  await scenarios.getByLabel("Sweep", { exact: true }).selectOption(stub.newer);
  return { rows, spreadRequests, scenarios };
}

test("the sensitivity is the server's, over the scenarios the filters keep, and says what is not swept", async ({ page }, testInfo) => {
  const { rows, spreadRequests, scenarios } = await open(page);
  await expect(page.getByRole("note").filter({ hasText: "Not swept" })).toHaveText(NOT_SWEPT);
  await expect(page.getByRole("rowheader", { name: "Vertical profile (B)" })).toBeVisible();
  const kept = rows.filter((row) => row.admissible).map((row) => row.config_hash).sort();
  await expect.poll(() => spreadRequests.at(-1)?.slice().sort()).toEqual(kept);

  await scenarios.getByRole("checkbox", { name: "merra2" }).first().uncheck();
  const narrowed = rows.filter((row) => row.admissible && row.reference_source !== "merra2").map((row) => row.config_hash).sort();
  await expect.poll(() => spreadRequests.at(-1)?.slice().sort()).toEqual(narrowed);
  await expect(page.getByRole("heading", { name: new RegExp(`over ${narrowed.length} scenarios`) })).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("interrogate-sensitivity-light.png") });
  await page.getByRole("button", { name: "Dark theme" }).click();
  await page.screenshot({ path: testInfo.outputPath("interrogate-sensitivity-dark.png") });
});

test("the gates panel says what each gate checks, what it found and what it excluded, whatever the admissibility filter", async ({ page }, testInfo) => {
  const refused = {
    ...sweepRows()[0],
    config_hash: "deadbeef00000000",
    status: "failed",
    admissible: false,
    error: "No concurrent months.",
  };
  const { rows } = await open(page, [refused]);
  await tab(page, "Gates").click();
  const completed = rows.filter((row) => row.status === "ok");
  const excluded = completed.filter((row) => !row.admissible);
  expect(excluded.length).toBeGreaterThan(0);

  // The excluded scenarios are counted although the scenario filters hide them by default.
  const counts = page.getByLabel("Admissibility counts");
  await expect(counts).toContainText(`Excluded by a gate${excluded.length}`);
  await expect(counts).toContainText("Could not run1");
  const tally = page.getByRole("table", { name: /Gate verdicts/ });
  const verdicts = tally.getByRole("row", { name: /Concurrent period/ }).getByRole("cell");
  await expect(verdicts.nth(0)).toHaveText(String(excluded.length));
  await expect(verdicts.nth(3)).toHaveText(String(completed.length - excluded.length));

  const gate = page.getByRole("region", { name: "Concurrent period" });
  await expect(gate).toContainText("Months of measured/reference overlap");
  const facts = gate.getByLabel("Concurrent period thresholds and observed range");
  await expect(facts).toContainText("concurrent months fail9");
  await expect(facts).toContainText("observed range7.250 to 12.500");
  await gate.getByText(`Excluded ${excluded.length} scenarios`).click();
  for (const row of excluded) await expect(gate.getByRole("rowheader", { name: row.config_hash.slice(0, 8) })).toBeVisible();

  await expect(page.getByRole("region", { name: /Could not run/ })).toContainText("No concurrent months.");
  await expect(page.getByRole("table", { name: /scenarios admissible/ })).toContainText("power_law_mean");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("interrogate-gates.png") });
});

test("two pinned scenarios sit side by side with their differences, and one loads into Model", async ({ page }, testInfo) => {
  const { rows, scenarios } = await open(page);
  const first = rows[0];
  const second = rows.find((row) => row.admissible && row.shear_model !== first.shear_model && row !== first);
  if (!second) throw new Error("no second shear model in the fixture");
  await scenarios.getByRole("button", { name: `Pin scenario ${first.config_hash.slice(0, 8)}` }).click();
  await scenarios.getByRole("button", { name: `Pin scenario ${second.config_hash.slice(0, 8)}` }).click();
  await tab(page, "Side by side").click();
  const pinned = page.getByRole("table", { name: /Pinned scenarios/ });
  await expect(pinned.getByRole("rowheader", { name: /Vertical profile \(B\) \(differs\)/ })).toBeVisible();
  await expect(page.getByRole("table", { name: /differing settings/ }).getByRole("rowheader", { name: "scenario.shear_model" })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("interrogate-pinned.png") });

  await page.route(/\/operations\/pipeline_from_scenario$/, (route) =>
    json(route, {
      sweep_id: "x", config_hash: first.config_hash,
      scenario: { shear_fit_policy: null, reference_policy: null, shear_model: "power_law_mean", reference_source: "era5", ltc_algorithm: "variance_ratio", hub_height_m: 120, analyst_shear_alpha: null },
      steps: [{ id: "shear_table", operation: "build_shear_table", parameters: {} }],
      prefix_matches: true,
    }),
  );
  await page.getByRole("button", { name: `Load ${first.config_hash.slice(0, 8)} into Model` }).click();
  await expect(page.getByRole("navigation", { name: "Phases" }).getByRole("button", { name: "Model", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("list", { name: "Steps in order" }).getByRole("button")).toHaveText(["shear_table"]);
});
