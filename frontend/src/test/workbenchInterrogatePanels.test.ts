import { describe, expect, it } from "vitest";

import { gateTally } from "../workbench/interrogate/GatesPanel";
import { differences, flatten } from "../workbench/interrogate/PinnedPanel";
import type { SweepRow } from "../workbench/interrogate/store";

const row = (hash: string, gates: Record<string, string>): SweepRow => ({
  config_hash: hash,
  admissible: true,
  status: "ok",
  ...Object.fromEntries(Object.entries(gates).flatMap(([gate, status]) => [[`gate_${gate}`, status], [`gate_${gate}_value`, 1]])),
});

describe("the gate tally", () => {
  it("counts each gate's verdicts over the rows in view, ignoring the measured values", () => {
    const tally = gateTally([
      row("a", { concurrent_period: "pass", roughness_clipping: "fail" }),
      row("b", { concurrent_period: "pass", roughness_clipping: "pass" }),
      row("c", { concurrent_period: "warn", roughness_clipping: "not_applicable" }),
    ]);
    expect(tally).toEqual([
      { gate: "concurrent_period", counts: { pass: 2, warn: 1 } },
      { gate: "roughness_clipping", counts: { fail: 1, pass: 1, not_applicable: 1 } },
    ]);
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
