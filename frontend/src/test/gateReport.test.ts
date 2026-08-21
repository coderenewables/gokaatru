// Gate summarisation — what the Gates view is built on.
//
// The question this answers for a reader is not "was this scenario excluded" (the row
// chips already say that) but "which check did the excluding, on what number, against
// what threshold". So the summary has to carry counts, the measured values, and the
// scenarios behind each verdict.
import { describe, expect, it } from "vitest";

import { gateValue, summariseGates } from "../lib/sweepAnalysis";
import { GATE_META, GATE_STATUS_MEANING, type ScenarioRow } from "../types/sweep";

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
    gate_extrapolation_ratio: "pass",
    gate_extrapolation_ratio_value: 1.2,
    ...overrides,
  } as ScenarioRow;
}

describe("summariseGates", () => {
  it("tallies every status and keeps the scenarios behind each verdict", () => {
    const rows = [
      row({ config_hash: "a" }),
      row({
        config_hash: "b",
        admissible: false,
        gate_extrapolation_ratio: "fail",
        gate_extrapolation_ratio_value: 3.1,
      }),
      row({
        config_hash: "c",
        gate_extrapolation_ratio: "warn",
        gate_extrapolation_ratio_value: 1.8,
      }),
    ];

    const [summary] = summariseGates(rows);
    expect(summary.gate).toBe("extrapolation_ratio");
    expect(summary.counts.pass).toBe(1);
    expect(summary.counts.fail).toBe(1);
    expect(summary.counts.warn).toBe(1);
    expect(summary.failedRows.map((r) => r.config_hash)).toEqual(["b"]);
    expect(summary.warnedRows.map((r) => r.config_hash)).toEqual(["c"]);
  });

  it("reports the observed range of the measured value", () => {
    const rows = [
      row({ config_hash: "a", gate_extrapolation_ratio_value: 1.2 }),
      row({ config_hash: "b", gate_extrapolation_ratio_value: 3.1 }),
    ];
    expect(summariseGates(rows)[0].valueRange).toEqual({ min: 1.2, max: 3.1 });
  });

  it("has no range when the gate never had anything to measure", () => {
    const rows = [
      row({
        config_hash: "a",
        gate_sector_records: "not_applicable",
        gate_sector_records_value: null,
      }),
    ];
    const sector = summariseGates(rows).find((entry) => entry.gate === "sector_records")!;
    expect(sector.valueRange).toBeNull();
    expect(sector.counts.not_applicable).toBe(1);
  });

  it("flags a gate that excluded every completed scenario", () => {
    // The case the first live run hit: a spread over zero scenarios is a measurement of
    // the threshold, not of the site, and the view has to say so.
    const rows = [
      row({ config_hash: "a", admissible: false, gate_extrapolation_ratio: "fail" }),
      row({ config_hash: "b", admissible: false, gate_extrapolation_ratio: "fail" }),
    ];
    expect(summariseGates(rows)[0].excludedEverything).toBe(true);
  });

  it("does not flag a gate that excluded only some", () => {
    const rows = [
      row({ config_hash: "a" }),
      row({ config_hash: "b", admissible: false, gate_extrapolation_ratio: "fail" }),
    ];
    expect(summariseGates(rows)[0].excludedEverything).toBe(false);
  });

  it("ignores scenarios that never ran", () => {
    // A scenario the pipeline refused never reached a gate, so counting it as a gate
    // failure would misattribute the exclusion.
    const rows = [
      row({ config_hash: "a" }),
      row({ config_hash: "z", status: "failed", admissible: false, error: "boom" }),
    ];
    const summary = summariseGates(rows)[0];
    expect(summary.counts.pass + summary.counts.fail).toBe(1);
  });

  it("orders excluding gates first", () => {
    const rows = [
      row({
        config_hash: "a",
        admissible: false,
        gate_extrapolation_ratio: "pass",
        gate_roughness_clipping: "fail",
        gate_roughness_clipping_value: 0.4,
      }),
      row({
        config_hash: "b",
        gate_extrapolation_ratio: "warn",
        gate_roughness_clipping: "not_applicable",
      }),
    ];
    expect(summariseGates(rows).map((entry) => entry.gate)).toEqual([
      "roughness_clipping",
      "extrapolation_ratio",
    ]);
  });

  it("discovers gates from the columns rather than a fixed list", () => {
    // A gate added on the backend must appear here without frontend work.
    const rows = [row({ config_hash: "a", gate_brand_new_check: "fail" } as never)];
    expect(summariseGates(rows).map((entry) => entry.gate)).toContain("brand_new_check");
  });

  it("returns nothing for an empty result set", () => {
    expect(summariseGates([])).toEqual([]);
  });
});

describe("gateValue", () => {
  it("reads the measured value for a gate", () => {
    expect(gateValue(row({ config_hash: "a", gate_extrapolation_ratio_value: 2.5 }), "extrapolation_ratio")).toBe(2.5);
  });

  it("returns null where the gate had nothing to measure", () => {
    expect(gateValue(row({ config_hash: "a", gate_sector_records_value: null }), "sector_records")).toBeNull();
    expect(gateValue(row({ config_hash: "a" }), "not_a_gate")).toBeNull();
  });
});

describe("gate metadata", () => {
  it("describes every gate the backend can emit", () => {
    // These names mirror `server/core/admissibility.py`. A gate without an entry renders
    // with no explanation, which defeats the purpose of the view.
    for (const gate of [
      "extrapolation_ratio",
      "concurrent_period",
      "mean_shear_alpha",
      "alpha_cell_dispersion",
      "shear_table_coverage",
      "roughness_clipping",
      "sector_records",
      "shear_provenance",
    ]) {
      expect(GATE_META[gate], gate).toBeDefined();
      expect(GATE_META[gate].measures.length).toBeGreaterThan(20);
      expect(GATE_META[gate].appliesTo.length).toBeGreaterThan(10);
    }
  });

  it("carries no entry for the removed R² gate", () => {
    // Removed deliberately (design doc §13.6) — R² is what least squares minimises by
    // construction, so gating on it ranks estimators rather than screening quality.
    expect(GATE_META.ltc_r_squared).toBeUndefined();
  });

  it("explains what each status means for admissibility", () => {
    expect(GATE_STATUS_MEANING.fail).toContain("Excluded");
    expect(GATE_STATUS_MEANING.warn).toContain("counted");
    expect(GATE_STATUS_MEANING.not_applicable).toContain("distinct from a pass");
    expect(GATE_STATUS_MEANING.marked).toContain("Never excludes");
  });
});
