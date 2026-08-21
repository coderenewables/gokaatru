// Client-side sweep analysis — design doc §9.3, §9.4.
//
// The property these tests exist for: statistics are computed over *admissible* rows
// only. An inadmissible scenario stays in the table and never enters a percentile, and
// getting that wrong would silently widen every reported interval with scenarios the
// gates rejected.
import { describe, expect, it } from "vitest";

import {
  admissibleRows,
  axisLevels,
  decomposeVariance,
  failedRows,
  filterRows,
  formatMetric,
  histogram,
  inadmissibleRows,
  metricValues,
  percentile,
  spreadStats,
  toCsv,
} from "../lib/sweepAnalysis";
import type { ScenarioRow } from "../types/sweep";

function row(overrides: Partial<ScenarioRow> & { config_hash: string }): ScenarioRow {
  return {
    fixed_prefix_hash: "prefix",
    status: "ok",
    admissible: true,
    failed_gates: "",
    warned_gates: "",
    marked_gates: "",
    error: null,
    shear_fit_policy: "nearest_2",
    reference_policy: "nearest_2",
    shear_model: "power_law_mean",
    reference_source: "era5",
    ltc_algorithm: "variance_ratio",
    long_term_mean_speed_mps: 8,
    ...overrides,
  } as ScenarioRow;
}

describe("row partitioning", () => {
  const rows = [
    row({ config_hash: "a" }),
    row({ config_hash: "b", admissible: false, failed_gates: "extrapolation_ratio" }),
    row({ config_hash: "c", status: "failed", admissible: false, error: "boom" }),
  ];

  it("separates admissible, excluded and failed rows", () => {
    expect(admissibleRows(rows).map((entry) => entry.config_hash)).toEqual(["a"]);
    expect(inadmissibleRows(rows).map((entry) => entry.config_hash)).toEqual(["b"]);
    expect(failedRows(rows).map((entry) => entry.config_hash)).toEqual(["c"]);
  });

  it("never counts a failed row as admissible", () => {
    // A failed scenario has admissible=false, but the status check is what must exclude
    // it — a future default flipping `admissible` must not let it into the statistics.
    expect(admissibleRows([row({ config_hash: "z", status: "failed" })])).toEqual([]);
  });
});

describe("spreadStats", () => {
  it("summarises a metric over the rows given", () => {
    const rows = [4, 6, 8, 10, 12].map((value, index) =>
      row({ config_hash: `r${index}`, long_term_mean_speed_mps: value }),
    );
    const stats = spreadStats(rows, "long_term_mean_speed_mps");
    expect(stats).not.toBeNull();
    expect(stats!.count).toBe(5);
    expect(stats!.min).toBe(4);
    expect(stats!.max).toBe(12);
    expect(stats!.p50).toBe(8);
    expect(stats!.mean).toBe(8);
    expect(stats!.rangePctOfMean).toBeCloseTo(100, 6);
  });

  it("returns null when no row carries the metric", () => {
    expect(spreadStats([row({ config_hash: "a", long_term_mean_speed_mps: null })], "long_term_mean_speed_mps")).toBeNull();
  });

  it("reports zero deviation for a single value rather than NaN", () => {
    const stats = spreadStats([row({ config_hash: "a" })], "long_term_mean_speed_mps");
    expect(stats!.std).toBe(0);
  });

  it("ignores non-finite values", () => {
    const rows = [
      row({ config_hash: "a", long_term_mean_speed_mps: 8 }),
      row({ config_hash: "b", long_term_mean_speed_mps: Number.NaN }),
    ];
    expect(metricValues(rows, "long_term_mean_speed_mps")).toEqual([8]);
  });
});

describe("percentile", () => {
  it("interpolates between neighbouring values", () => {
    expect(percentile([0, 10], 0.5)).toBe(5);
    expect(percentile([0, 10, 20, 30], 0.1)).toBeCloseTo(3, 6);
  });

  it("handles degenerate inputs", () => {
    expect(percentile([], 0.5)).toBeNaN();
    expect(percentile([7], 0.9)).toBe(7);
  });
});

describe("decomposeVariance", () => {
  it("attributes the spread to the axis that actually moves the answer", () => {
    // Speed depends only on the LTC method here; the shear model is noise-free constant.
    const rows = [
      row({ config_hash: "a", ltc_algorithm: "variance_ratio", long_term_mean_speed_mps: 8 }),
      row({ config_hash: "b", ltc_algorithm: "variance_ratio", long_term_mean_speed_mps: 8 }),
      row({ config_hash: "c", ltc_algorithm: "linear_least_squares", long_term_mean_speed_mps: 10 }),
      row({ config_hash: "d", ltc_algorithm: "linear_least_squares", long_term_mean_speed_mps: 10 }),
    ];
    const contributions = decomposeVariance(rows, "long_term_mean_speed_mps");
    expect(contributions[0].axis).toBe("ltc_algorithm");
    expect(contributions[0].share).toBeCloseTo(1, 6);
    expect(contributions[0].swing).toBeCloseTo(2, 6);
  });

  it("gives a single-level axis no share", () => {
    const rows = [
      row({ config_hash: "a", long_term_mean_speed_mps: 8 }),
      row({ config_hash: "b", long_term_mean_speed_mps: 9 }),
    ];
    const shear = decomposeVariance(rows, "long_term_mean_speed_mps").find(
      (entry) => entry.axis === "shear_model",
    );
    expect(shear!.levels).toBe(1);
    expect(shear!.share).toBe(0);
  });

  it("returns nothing when there is not enough to decompose", () => {
    expect(decomposeVariance([row({ config_hash: "a" })], "long_term_mean_speed_mps")).toEqual([]);
  });

  it("reports level means with the count behind each", () => {
    const rows = [
      row({ config_hash: "a", reference_source: "era5", long_term_mean_speed_mps: 8 }),
      row({ config_hash: "b", reference_source: "merra2", long_term_mean_speed_mps: 9 }),
      row({ config_hash: "c", reference_source: "merra2", long_term_mean_speed_mps: 11 }),
    ];
    const entry = decomposeVariance(rows, "long_term_mean_speed_mps").find(
      (item) => item.axis === "reference_source",
    )!;
    const merra = entry.levelMeans.find((level) => level.level === "merra2")!;
    expect(merra.mean).toBe(10);
    expect(merra.count).toBe(2);
  });
});

describe("filtering", () => {
  const rows = [
    row({ config_hash: "a", reference_source: "era5" }),
    row({ config_hash: "b", reference_source: "merra2" }),
  ];

  it("filters by axis level", () => {
    expect(filterRows(rows, { reference_source: ["merra2"] }).map((r) => r.config_hash)).toEqual(["b"]);
  });

  it("treats an empty selection as no filter", () => {
    expect(filterRows(rows, { reference_source: [] })).toHaveLength(2);
    expect(filterRows(rows, {})).toHaveLength(2);
  });

  it("lists the distinct levels present", () => {
    expect(axisLevels(rows, "reference_source")).toEqual(["era5", "merra2"]);
  });
});

describe("presentation helpers", () => {
  it("formats a metric with its unit and precision", () => {
    expect(formatMetric(8.1234, "long_term_mean_speed_mps")).toBe("8.123 m/s");
    expect(formatMetric(null, "long_term_mean_speed_mps")).toBe("—");
    expect(formatMetric(0.4321, "capacity_factor")).toBe("0.4321");
  });

  it("bins values for the distribution panel", () => {
    const bins = histogram([1, 2, 3, 4], 2);
    expect(bins).toHaveLength(2);
    expect(bins.reduce((total, bin) => total + bin.count, 0)).toBe(4);
  });

  it("returns a single bin when every value is identical", () => {
    expect(histogram([5, 5, 5], 8)).toHaveLength(1);
  });

  it("writes CSV with quoted fields where needed", () => {
    const csv = toCsv([row({ config_hash: "a", error: "failed, badly" })]);
    const [header, body] = csv.split("\n");
    expect(header).toContain("config_hash");
    expect(body).toContain('"failed, badly"');
  });

  it("returns empty CSV for no rows", () => {
    expect(toCsv([])).toBe("");
  });
});
