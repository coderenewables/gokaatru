import { buildScenarioComparison } from "../lib/scenarioCompare";

describe("scenario comparison", () => {
  it("builds ordered metric rows and config diffs for named runs", () => {
    const comparison = buildScenarioComparison([
      {
        label: "Run Baseline",
        scenario: {
          name: "Baseline",
          created_at: "2026-05-20T09:00:00Z",
          config: {
            ltc_algorithm: "speedsort",
            shear_method: "power_law",
            hub_height_m: 120,
          },
          results: {
            long_term_mean_speed: 8.4,
            total_uncertainty_pct: 9.1,
            p50: 1,
          },
        },
      },
      {
        label: "Run 2",
        scenario: {
          name: "Run 2",
          created_at: "2026-05-20T10:00:00Z",
          config: {
            ltc_algorithm: "variance_ratio",
            shear_method: "power_law",
            hub_height_m: 125,
          },
          results: {
            long_term_mean_speed: 8.8,
            total_uncertainty_pct: 8.6,
            p50: 1,
          },
        },
      },
    ]);

    expect(comparison).not.toBeNull();
    expect(comparison?.labels).toEqual(["Run Baseline", "Run 2"]);
    expect(comparison?.metrics.map((metric) => metric.key)).toEqual([
      "long_term_mean_speed",
      "total_uncertainty_pct",
      "p50",
    ]);
    expect(comparison?.metrics[0].values["Run Baseline"]).toBe(8.4);
    expect(comparison?.metrics[0].values["Run 2"]).toBe(8.8);
    expect(comparison?.diffs["Run Baseline<->Run 2"]).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: "hub_height_m", baseline: 120, compare: 125 }),
        expect.objectContaining({ key: "ltc_algorithm", baseline: "speedsort", compare: "variance_ratio" }),
      ]),
    );
  });

  it("returns null when fewer than two runs are selected", () => {
    expect(
      buildScenarioComparison([
        {
          label: "Run Baseline",
          scenario: {
            name: "Baseline",
            created_at: "2026-05-20T09:00:00Z",
            config: {},
            results: {},
          },
        },
      ]),
    ).toBeNull();
  });
});
