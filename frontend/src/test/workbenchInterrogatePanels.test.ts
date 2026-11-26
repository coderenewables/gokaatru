import { describe, expect, it } from "vitest";

import { GATE_META, GATE_STATUS_MEANING } from "../types/sweep";
import { toCsv } from "../workbench/interrogate/export";
import { gateValue, summariseGates } from "../workbench/interrogate/GatesPanel";
import { differences, flatten } from "../workbench/interrogate/PinnedPanel";
import { NO_TERMS, filterRows, type SweepRow } from "../workbench/interrogate/store";

// The gate summary carries what the retired Gate report showed (P3-15a): counts, the measured
// range, the scenarios behind each verdict and a gate that excluded everything.

const row = (hash: string, fields: Record<string, string | number | boolean | null> = {}): SweepRow => ({
  config_hash: hash,
  admissible: true,
  status: "ok",
  gate_extrapolation_ratio: "pass",
  gate_extrapolation_ratio_value: 1.2,
  ...fields,
});

describe("the gate summary", () => {
  it("tallies every verdict and keeps the scenarios behind each", () => {
    const [summary] = summariseGates([
      row("a"),
      row("b", { admissible: false, gate_extrapolation_ratio: "fail", gate_extrapolation_ratio_value: 3.1 }),
      row("c", { gate_extrapolation_ratio: "warn", gate_extrapolation_ratio_value: 1.8 }),
    ]);
    expect(summary.gate).toBe("extrapolation_ratio");
    expect(summary.counts).toEqual({ pass: 1, warn: 1, fail: 1, not_applicable: 0, marked: 0 });
    expect(summary.failed.map((r) => r.config_hash)).toEqual(["b"]);
    expect(summary.warned.map((r) => r.config_hash)).toEqual(["c"]);
    expect(summary.valueRange).toEqual({ min: 1.2, max: 3.1 });
  });

  it("has no range where the gate had nothing to measure", () => {
    const sector = summariseGates([row("a", { gate_sector_records: "not_applicable", gate_sector_records_value: null })]).find(
      (entry) => entry.gate === "sector_records",
    );
    expect(sector?.valueRange).toBeNull();
    expect(sector?.counts.not_applicable).toBe(1);
  });

  it("says when a gate excluded every completed scenario, and not when it excluded some", () => {
    const fail = { admissible: false, gate_extrapolation_ratio: "fail" };
    expect(summariseGates([row("a", fail), row("b", fail)])[0].excludedEverything).toBe(true);
    expect(summariseGates([row("a"), row("b", fail)])[0].excludedEverything).toBe(false);
  });

  it("leaves out a scenario that never ran: it reached no gate", () => {
    const [summary] = summariseGates([row("a"), row("z", { status: "failed", admissible: false, gate_extrapolation_ratio: "fail" })]);
    expect(summary.counts.pass + summary.counts.fail).toBe(1);
  });

  it("lists the gates that excluded something first, then those that warned", () => {
    const rows = [
      row("a", { admissible: false, gate_roughness_clipping: "fail", gate_roughness_clipping_value: 0.4 }),
      row("b", { gate_extrapolation_ratio: "warn", gate_roughness_clipping: "not_applicable", gate_alpha_cell_dispersion: "pass" }),
    ];
    expect(summariseGates(rows).map((entry) => entry.gate)).toEqual(["roughness_clipping", "extrapolation_ratio", "alpha_cell_dispersion"]);
  });

  it("finds a gate from the columns, so one added on the server needs no change here", () => {
    expect(summariseGates([row("a", { gate_brand_new_check: "fail" })]).map((entry) => entry.gate)).toContain("brand_new_check");
    expect(summariseGates([])).toEqual([]);
  });

  it("reads a gate's measured value, or nothing", () => {
    expect(gateValue(row("a", { gate_extrapolation_ratio_value: 2.5 }), "extrapolation_ratio")).toBe(2.5);
    expect(gateValue(row("a"), "not_a_gate")).toBeNull();
  });

  it("is counted over the scenarios the gates excluded too, whatever the admissibility filter", () => {
    const rows = [row("a"), row("b", { admissible: false, gate_extrapolation_ratio: "fail" })];
    expect(filterRows(rows, NO_TERMS).map((r) => r.config_hash)).toEqual(["a"]);
    expect(filterRows(rows, NO_TERMS, "admissibility").map((r) => r.config_hash)).toEqual(["a", "b"]);
  });
});

describe("what a gate and a verdict mean", () => {
  // Which gates the server emits is held against GATE_META by tests/test_gate_descriptions.py.
  it("describes each gate in words a reader can act on", () => {
    for (const [gate, meta] of Object.entries(GATE_META)) {
      expect(meta.measures.length, gate).toBeGreaterThan(20);
      expect(meta.appliesTo.length, gate).toBeGreaterThan(10);
    }
  });

  it("carries no entry for the removed R² gate", () => {
    // Removed deliberately (design doc §13.6): least squares minimises it by construction, so
    // gating on it ranks estimators rather than screening quality.
    expect(GATE_META.ltc_r_squared).toBeUndefined();
  });

  it("says what each verdict means for whether a scenario counts", () => {
    expect(GATE_STATUS_MEANING.fail).toContain("Excluded");
    expect(GATE_STATUS_MEANING.warn).toContain("counted");
    expect(GATE_STATUS_MEANING.not_applicable).toContain("distinct from a pass");
    expect(GATE_STATUS_MEANING.marked).toContain("Never excludes");
  });
});

describe("the scenarios as CSV", () => {
  it("takes every column any row has, so a failed first row drops none", () => {
    const csv = toCsv([
      { config_hash: "a", status: "failed", error: "No concurrent months." },
      { config_hash: "b", status: "ok", long_term_mean_speed_mps: 7.25, gate_concurrent_period: "pass" },
    ]);
    expect(csv).toBe(
      "config_hash,status,error,long_term_mean_speed_mps,gate_concurrent_period\n" +
        "a,failed,No concurrent months.,,\n" +
        "b,ok,,7.25,pass\n",
    );
  });

  it("quotes a value holding a comma, a quote or a line break, and leaves a missing value empty", () => {
    expect(toCsv([{ a: 'say "x", then\ny', b: null, c: true }])).toBe('a,b,c\n"say ""x"", then\ny",,true\n');
    expect(toCsv([])).toBe("");
  });
});

describe("two configurations side by side", () => {
  it("flattens every leaf to a dotted path", () => {
    expect(flatten({ scenario: { shear_model: "power_law_mean", heights: [80, 100] }, empty: {} })).toEqual({
      "scenario.shear_model": '"power_law_mean"',
      "scenario.heights.0": "80",
      "scenario.heights.1": "100",
      empty: "{}",
    });
  });

  it("lists the paths that differ, and one only one has as absent", () => {
    const left = flatten({ a: 1, b: { c: "x" }, only_left: true });
    const right = flatten({ a: 1, b: { c: "y" }, only_right: 2 });
    expect(differences(left, right)).toEqual([
      ["b.c", '"x"', '"y"'],
      ["only_left", "true", "(absent)"],
      ["only_right", "(absent)", "2"],
    ]);
  });
});
