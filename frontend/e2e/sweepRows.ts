import type { Page, Route } from "@playwright/test";

// A sweep's rows for the Interrogate tests, which cannot run a real sweep: 24 scenarios over
// three shear-fit policies, two shear models, two reference sources and two corrections. The
// four that fit on the upper sensors and use the variance-ratio correction are inadmissible.
// Metrics are a deterministic function of the levels, so a test can name what a brush keeps.

export interface FakeRow {
  config_hash: string;
  fixed_prefix_hash: string;
  status: "ok" | "failed";
  admissible: boolean;
  shear_fit_policy: string;
  reference_policy: string;
  shear_model: string;
  reference_source: string;
  ltc_algorithm: string;
  long_term_mean_speed_mps: number;
  indicative_gross_aep_mwh: number;
  capacity_factor: number;
  total_uncertainty_pct: number;
  ltc_r_squared: number | null;
  failed_gates: string;
  warned_gates: string;
  marked_gates: string;
  error: null;
}

const POLICIES = ["all_sensors", "lower_pair", "upper_pair"];
const SHEAR = ["power_law", "log_law"];
const SOURCES = ["era5", "merra2"];
const LTC = ["linear", "variance_ratio"];

export function sweepRows(): FakeRow[] {
  const rows: FakeRow[] = [];
  for (const [p, policy] of POLICIES.entries()) {
    for (const [s, shear] of SHEAR.entries()) {
      for (const [r, source] of SOURCES.entries()) {
        for (const [l, ltc] of LTC.entries()) {
          const n = rows.length;
          const speed = 6.5 + 0.25 * p + 0.8 * s + 0.35 * r + 0.15 * l + 0.01 * (n % 3);
          rows.push({
            config_hash: `c0ffee${String(n).padStart(2, "0")}ab12cd34`,
            fixed_prefix_hash: "prefix000000abcd",
            status: "ok",
            admissible: !(policy === "upper_pair" && ltc === "variance_ratio"),
            shear_fit_policy: policy,
            reference_policy: "top_sensor",
            shear_model: shear,
            reference_source: source,
            ltc_algorithm: ltc,
            long_term_mean_speed_mps: Number(speed.toFixed(3)),
            indicative_gross_aep_mwh: Math.round(9000 + 1900 * (speed - 6.5)),
            capacity_factor: Number((0.28 + 0.045 * (speed - 6.5)).toFixed(4)),
            total_uncertainty_pct: Number((6 + 0.4 * p + 0.5 * s - 0.3 * r + 0.2 * l).toFixed(2)),
            ltc_r_squared: l === 0 ? Number((0.8 + 0.02 * r).toFixed(3)) : null,
            failed_gates: "",
            warned_gates: "",
            marked_gates: "",
            error: null,
          });
        }
      }
    }
  }
  return rows;
}

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

/** Answer the campaign's sweep list and each sweep's table from the fixture; the newer sweep
 * holds every row, the older one the first twelve. */
export async function stubSweeps(page: Page): Promise<{ newer: string; older: string; rows: FakeRow[] }> {
  const rows = sweepRows();
  const newer = "sweep-20261126-b";
  const older = "sweep-20261125-a";
  const counts = (n: number) => ({ planned: n, run: n, completed: n, failed: 0 });
  await page.route(/\/api\/sessions\/[^/]+\/sweep$/, (route) =>
    json(route, {
      sweeps: [
        { sweep_id: newer, started_at: "2026-11-26T09:00:00", finished_at: "2026-11-26T09:10:00", counts: counts(24), fixed_prefix_hash: "p", in_progress: false },
        { sweep_id: older, started_at: "2026-11-25T09:00:00", finished_at: "2026-11-25T09:05:00", counts: counts(12), fixed_prefix_hash: "p", in_progress: false },
      ],
    }),
  );
  await page.route(/\/api\/sessions\/[^/]+\/sweep\/sweep-[^/]+$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const results = id === older ? rows.slice(0, 12) : rows;
    return json(route, { manifest: { sweep_id: id, counts: counts(results.length), scenarios: [] }, results });
  });
  return { newer, older, rows };
}
