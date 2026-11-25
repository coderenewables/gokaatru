import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

import { newCampaign, pageErrors } from "./fixtures";
import OLD_DESIGNER_RUNS from "./oldDesignerRuns.json" with { type: "json" };

// The Run phase (P3-13, decisions/0015.6): the matrix sweep designer and the run monitor. No
// reanalysis can be seeded without the network, so the sweep endpoints are faked in the
// browser as reanalysis.spec.ts fakes BrightHub: /axes, /estimate and /run/stream. The server's
// own behaviour is covered by pytest; what is held here is the interface and, in the gate
// test, that it asks for exactly what the old interface asked for.

const level = (name: string, available = true, extra: object = {}) => ({ name, available, ...extra });

// A campaign with no boom redundancy, one policy that resolves to a single height, no MERRA-2
// and no roughness length: every preset names something it cannot run.
const AXES = {
  sensor_policies: [
    level("nearest_2", true, { resolved_columns: ["Spd_80m", "Spd_100m"], can_fit_shear: true }),
    level("availability_90", true, { resolved_columns: ["Spd_60m", "Spd_80m", "Spd_100m"], can_fit_shear: true }),
    level("redundant_boom", false, { reason: "No heights carry a second boom's sensor." }),
    level("widest_lever", true, { resolved_columns: ["Spd_60m", "Spd_100m"], can_fit_shear: true }),
  ],
  shear_models: [
    level("power_law_mean"),
    level("power_law_median"),
    level("power_law_momm"),
    level("power_law_constant"),
    level("log_law_mean", false, { reason: "Needs a roughness length, which this campaign has none of." }),
  ],
  reference_sources: [level("era5"), level("merra2", false, { reason: "No MERRA-2 series has been interpolated to the site." })],
  power_curves: [],
  known_sensor_policies: [],
  default_thresholds: {},
};

const MANIFEST = {
  sweep_id: "sweep-fake-0001",
  started_at: "2026-11-26T10:00:00+00:00",
  finished_at: "2026-11-26T10:00:09+00:00",
  stopped_early: false,
  fixed_prefix_hash: "bc0e680184f7bc7d",
  not_swept_statement:
    "Not swept: wind direction, temperature and air density. Every scenario in this sweep uses the same ones, so the spread covers the wind-speed chain only: sensor choice, shear, reference source and long-term method.",
  gate_failures: { roughness_clipping: 1 },
  counts: { planned: 4, run: 3, completed: 2, failed: 1, admissible: 1, inadmissible: 1, duplicates_skipped: 1 },
  duplicates_skipped: [{ shear_fit_policy: "availability_90", reference_policy: "nearest_2", same_as: "aaaaaaaabbbbcccc" }],
  scenarios: [],
};

const PREFIX = ["nearest_2", "power_law_mean", null];
const STREAM = [
  { event: "sweep_started", completed: 0, total: 4, config_hash: null },
  { event: "prefix_started", completed: 0, total: 4, config_hash: null, detail: { shear_prefix: PREFIX } },
  { event: "prefix_completed", completed: 0, total: 4, config_hash: null, detail: { shear_prefix: PREFIX } },
  { event: "scenario_completed", completed: 1, total: 4, config_hash: "aaaaaaaabbbbcccc", detail: { admissible: true } },
  { event: "scenario_completed", completed: 2, total: 4, config_hash: "11112222aaaabbbb", detail: { admissible: false } },
  {
    event: "scenario_skipped_duplicate",
    completed: 3,
    total: 4,
    config_hash: null,
    detail: { shear_fit_policy: "availability_90", reference_policy: "nearest_2", same_as: "aaaaaaaabbbbcccc" },
  },
  { event: "scenario_failed", completed: 4, total: 4, config_hash: "99998888aaaabbbb", detail: { error: "No concurrent months." }, error: "No concurrent months." },
  { event: "sweep_finished", completed: 4, total: 4, config_hash: null, manifest: MANIFEST },
];

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const leafAxes = (a: string, b: string, c: string, d: string, e: string) => ({
  shear_fit_policy: a,
  reference_policy: b,
  shear_model: c,
  reference_source: d,
  ltc_algorithm: e,
});

/** The estimate for a request: the product of the ticked levels, with two leaves skipped as
 * duplicates and one refused once the design is big enough to have them. */
function estimateFor(body: Record<string, string[]>) {
  const planned = ["shear_fit_policies", "reference_policies", "shear_models", "reference_sources", "ltc_algorithms"].reduce(
    (product, key) => product * body[key].length,
    1,
  );
  const big = planned >= 4;
  const duplicates = big
    ? [{ ...leafAxes("availability_90", "nearest_2", "power_law_mean", "era5", "variance_ratio"), same_as: leafAxes("nearest_2", "nearest_2", "power_law_mean", "era5", "variance_ratio") }]
    : [];
  const unavailable = big
    ? [{ ...leafAxes("widest_lever", "nearest_2", "power_law_mean", "era5", "xgboost"), stage: "ltc", reason: "XGBoost is not installed on this server." }]
    : [];
  return {
    leaf_count: planned,
    prefix_count: body.shear_fit_policies.length * body.shear_models.length,
    spec: body,
    counts: {
      planned,
      prefixes: body.shear_fit_policies.length * body.shear_models.length,
      would_run: planned - duplicates.length - unavailable.length,
      duplicates: duplicates.length,
      unavailable: unavailable.length,
    },
    duplicates,
    unavailable,
    duplicates_basis: "A leaf is a duplicate when it resolves to the same sensors, model, source and method as one that runs first.",
    refusals_basis: "A leaf is refused when a stage cannot run for it, found with the code the run uses.",
  };
}

interface Seen {
  estimates: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
}

async function fakeSweep(page: Page, options: { streamBody?: string } = {}): Promise<Seen> {
  const seen: Seen = { estimates: [], runs: [] };
  await page.route("**/api/sessions/*/sweep/axes", (route) => json(route, AXES));
  await page.route("**/api/sessions/*/sweep/estimate", (route) => {
    const body = route.request().postDataJSON() as Record<string, string[]>;
    seen.estimates.push(body);
    return json(route, estimateFor(body));
  });
  await page.route("**/api/sessions/*/sweep/run/stream", (route) => {
    seen.runs.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: options.streamBody ?? STREAM.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
    });
  });
  return seen;
}

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map(
      (violation) => `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(" ")).join("; ")}`,
    ),
  ).toEqual([]);
}

async function openRun(page: Page, name: string) {
  const { projectId, sessionId } = await newCampaign(page, `${name} ${Date.now()}`);
  await page.goto(`/?project=${projectId}&campaign=${sessionId}&phase=run`);
  await expect(page.getByRole("group", { name: "Presets" })).toBeVisible();
}

const cell = (page: Page, axis: string, level: string) =>
  page.getByRole("group", { name: axis }).getByRole("checkbox", { name: level });

const PRESET_NAMES = ["Quick look", "Standard EYA", "Exhaustive"] as const;

test("the matrix shows each axis's levels, and disables with its reason what the campaign cannot run", async ({ page }) => {
  const errors = pageErrors(page);
  await fakeSweep(page);
  await openRun(page, "Matrix");

  for (const axis of ["Shear-fit sensors (A1)", "Extrapolation reference (A2)", "Vertical profile (B)", "Long-term reference (C)", "LTC method (D)"]) {
    await expect(page.getByRole("group", { name: axis })).toBeVisible();
  }
  // The default design: ticked cells, and the rest free to tick.
  await expect(cell(page, "Shear-fit sensors (A1)", "nearest 2")).toBeChecked();
  await expect(cell(page, "Long-term reference (C)", "era5")).toBeChecked();
  await expect(cell(page, "LTC method (D)", "speedsort")).toBeEnabled();

  // A disabled level and its reason, in the text of the page, not only a tooltip.
  const boom = cell(page, "Shear-fit sensors (A1)", "redundant boom");
  await expect(boom).toBeDisabled();
  await expect(page.getByRole("group", { name: "Shear-fit sensors (A1)" })).toContainText("No heights carry a second boom's sensor.");
  await expect(cell(page, "Long-term reference (C)", "merra2")).toBeDisabled();
  await expect(page.getByRole("group", { name: "Long-term reference (C)" })).toContainText("No MERRA-2 series has been interpolated");
  await expect(cell(page, "Vertical profile (B)", "log law mean")).toBeDisabled();
  // The carried-over default asked for MERRA-2, which this campaign cannot run: dropped and said so.
  await expect(page.getByRole("status").filter({ hasText: "Left out" })).toContainText("merra2");
  expect(errors).toEqual([]);
});

test("a preset is intersected with what the campaign can run, and the dropped levels are named", async ({ page }) => {
  const errors = pageErrors(page);
  await fakeSweep(page);
  await openRun(page, "Preset");

  await page.getByRole("button", { name: "Exhaustive" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Left out" })).toContainText("redundant_boom");
  await expect(page.getByRole("status").filter({ hasText: "Left out" })).toContainText("log_law_mean");
  await expect(page.getByRole("status").filter({ hasText: "Left out" })).toContainText("merra2");
  await expect(cell(page, "Shear-fit sensors (A1)", "widest lever")).toBeChecked();
  await expect(cell(page, "Shear-fit sensors (A1)", "availability 90")).toBeChecked();
  await expect(cell(page, "Vertical profile (B)", "power law constant")).toBeChecked();
  await expect(cell(page, "LTC method (D)", "xgboost")).toBeChecked();

  await page.getByRole("button", { name: "Quick look" }).click();
  await expect(cell(page, "Shear-fit sensors (A1)", "widest lever")).not.toBeChecked();
  await expect(cell(page, "LTC method (D)", "xgboost")).not.toBeChecked();
  await expect(cell(page, "LTC method (D)", "variance ratio")).toBeChecked();
  expect(errors).toEqual([]);
});

test("the live estimate counts the design, lists its duplicates and refusals, and follows a tick", async ({ page }) => {
  const errors = pageErrors(page);
  const seen = await fakeSweep(page);
  await openRun(page, "Estimate");

  await page.getByRole("button", { name: "Standard EYA" }).click();
  // 2 x 2 x 2 x 1 x 3 = 24 planned, 4 shear tables, one duplicate and one refusal (the fake's).
  const counts = page.getByLabel("What the design would run");
  await expect(counts).toContainText("Planned scenarios24");
  await expect(counts).toContainText("Shear tables4");
  await expect(counts).toContainText("Would run22");
  await expect(counts).toContainText("Duplicates1");
  await expect(counts).toContainText("Unavailable1");

  await page.getByText("1 skipped as duplicates").click();
  await expect(page.getByText("availability_90 / nearest_2 / power_law_mean / era5 / variance_ratio")).toBeVisible();
  await expect(page.getByText("repeats nearest_2 / nearest_2 / power_law_mean / era5 / variance_ratio")).toBeVisible();
  await expect(page.getByText("A leaf is a duplicate when")).toBeVisible();
  await page.getByText("1 refused").click();
  await expect(page.getByText("ltc: XGBoost is not installed on this server.")).toBeVisible();
  await expect(page.getByText("A leaf is refused when a stage")).toBeVisible();

  await cell(page, "LTC method (D)", "speedsort").check();
  await expect(counts).toContainText("Planned scenarios32");
  // Each pricing asked the server for exactly the ticked levels.
  expect(seen.estimates.at(-1)?.ltc_algorithms).toEqual(["variance_ratio", "linear_least_squares", "total_least_squares", "speedsort"]);

  // An emptied axis cannot be priced or run.
  for (const name of ["variance ratio", "linear least squares", "total least squares", "speedsort"]) {
    await cell(page, "LTC method (D)", name).uncheck();
  }
  await expect(page.getByText("Tick at least one level on every axis.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run sweep" })).toBeDisabled();
  expect(errors).toEqual([]);
});

for (const theme of ["light", "dark"] as const) {
  test(`running shows each event and the outcome with its not-swept sentence (${theme})`, async ({ page }, testInfo) => {
    const errors = pageErrors(page);
    const seen = await fakeSweep(page);
    await openRun(page, `Run ${theme}`);
    if (theme === "dark") {
      await page.getByRole("button", { name: "Dark theme" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    }
    await page.getByRole("button", { name: "Standard EYA" }).click();
    await expect(page.getByLabel("What the design would run")).toContainText("Planned scenarios24");
    await page.getByRole("button", { name: "Run sweep" }).click();

    const monitor = page.getByLabel("Events");
    await expect(page.getByRole("status").filter({ hasText: "Finished" })).toContainText("4 of 4 scenarios accounted for");
    await expect(monitor).toContainText("Scenario aaaaaaaa completed");
    await expect(monitor).toContainText("Scenario 11112222 completed, inadmissible");
    await expect(monitor).toContainText("Skipped availability_90 / nearest_2: it repeats aaaaaaaa");
    await expect(monitor).toContainText("Scenario 99998888 failed: No concurrent months.");
    await expect(monitor).toContainText("Shear table started: nearest_2 / power_law_mean");

    const outcome = page.getByLabel("Outcome");
    await expect(outcome).toContainText("sweep-fake-0001");
    await expect(outcome).toContainText("Duplicates skipped1");
    await expect(outcome.getByRole("row", { name: /roughness_clipping/ })).toBeVisible();
    await expect(outcome).toContainText(MANIFEST.not_swept_statement);

    expect(seen.runs).toHaveLength(1);
    expect(seen.runs[0].ltc_algorithms).toEqual(["variance_ratio", "linear_least_squares", "total_least_squares"]);
    await expectNoAxeViolations(page);
    await page.screenshot({ path: testInfo.outputPath(`run-${theme}.png`) });
    expect(errors).toEqual([]);
  });
}

test("a sweep that ends in an error says so, and the design can be run again", async ({ page }) => {
  const errors = pageErrors(page);
  const streamBody = [STREAM[0], { event: "sweep_error", error: "ValueError('no reanalysis')" }]
    .map((event) => `data: ${JSON.stringify(event)}\n\n`)
    .join("");
  await fakeSweep(page, { streamBody });
  await openRun(page, "Error");
  await page.getByRole("button", { name: "Run sweep" }).click();
  await expect(page.getByText("The sweep ended with an error")).toContainText("ValueError('no reanalysis')");
  await expect(page.getByRole("button", { name: "Run sweep" })).toBeEnabled();
  expect(errors).toEqual([]);
});

// THE GATE CHECK (P3-13): "a sweep designed in the new interface matches the old one row for
// row". The server is deterministic (pytest), so the same request is the same rows: for each
// preset, on the same /axes, the request the new designer posts to /sweep/run/stream equals the
// old interface's. Until P3-16 retired it, this test drove the old interface live; its last run
// passed for all three presets and recorded what the old designer posted, which is held here.
for (const preset of PRESET_NAMES) {
  test(`gate: the new designer's ${preset} sweep posts the same request as the old interface's`, async ({ page }) => {
    const seen = await fakeSweep(page);

    const { projectId, sessionId } = await newCampaign(page, `Gate ${preset} ${Date.now()}`);
    await page.goto(`/?project=${projectId}&campaign=${sessionId}&phase=run`);
    await page.getByRole("button", { name: preset }).click();
    await expect(page.getByLabel("What the design would run")).toBeVisible();
    await page.getByRole("button", { name: "Run sweep" }).click();
    await expect(page.getByLabel("Outcome")).toBeVisible();
    expect(seen.runs).toHaveLength(1);

    const [fresh] = seen.runs;
    expect(fresh).toEqual(OLD_DESIGNER_RUNS[preset]);
    // Not vacuous: the request names levels, and Exhaustive's dropped ones are absent from it.
    expect((fresh.ltc_algorithms as string[]).length).toBeGreaterThan(0);
    expect(JSON.stringify(fresh)).not.toContain("redundant_boom");
  });
}
