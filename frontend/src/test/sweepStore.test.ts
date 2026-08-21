// Sweep store and designer gating — design doc §9.1, §3.A.1.
//
// The two rules the designer must not get wrong: a level this session cannot run must
// block the launch rather than fail every leaf, and a shear-fit policy that resolves to
// one height must demand an exponent rather than inventing one.
import { beforeEach, describe, expect, it } from "vitest";

import {
  SWEEP_PRESETS,
  requiresAnalystShear,
  unavailableSelections,
  useSweepStore,
  type SweepSelection,
} from "../store/useSweepStore";
import type { SweepAxes } from "../types/sweep";

function axes(overrides: Partial<SweepAxes> = {}): SweepAxes {
  return {
    sensor_policies: [
      { name: "nearest_2", available: true, can_fit_shear: true },
      { name: "availability_90", available: true, can_fit_shear: true },
      {
        name: "redundant_boom",
        available: false,
        reason: "No height carries more than one wind-speed sensor",
      },
      { name: "widest_lever", available: true, can_fit_shear: true },
    ],
    shear_models: [
      { name: "power_law_mean", available: true },
      { name: "power_law_sector_12", available: false, reason: "extrapolation reads only the table" },
    ],
    reference_sources: [
      { name: "era5", available: true },
      { name: "merra2", available: true },
    ],
    power_curves: ["generic-3.0MW-130m-IIA"],
    known_sensor_policies: ["nearest_2", "availability_90", "redundant_boom", "widest_lever"],
    default_thresholds: { extrapolation_ratio_fail: 2.0 },
    ...overrides,
  };
}

function selection(overrides: Partial<SweepSelection> = {}): SweepSelection {
  return {
    shearFitPolicies: ["nearest_2"],
    referencePolicies: ["nearest_2"],
    shearModels: ["power_law_mean"],
    referenceSources: ["era5"],
    ltcAlgorithms: ["variance_ratio"],
    analystShearAlpha: null,
    thresholds: {},
    ...overrides,
  };
}

describe("unavailableSelections", () => {
  it("names every chosen level this session cannot run", () => {
    const chosen = selection({
      shearFitPolicies: ["nearest_2", "redundant_boom"],
      shearModels: ["power_law_sector_12"],
    });
    expect(unavailableSelections(chosen, axes()).sort()).toEqual([
      "power_law_sector_12",
      "redundant_boom",
    ]);
  });

  it("is empty when every chosen level is available", () => {
    expect(unavailableSelections(selection(), axes())).toEqual([]);
  });

  it("blocks nothing before the axes have loaded", () => {
    expect(unavailableSelections(selection(), null)).toEqual([]);
  });
});

describe("requiresAnalystShear", () => {
  it("is true when an available fit policy resolves to a single height", () => {
    const single = axes({
      sensor_policies: [
        { name: "redundant_boom", available: true, can_fit_shear: false },
        { name: "nearest_2", available: true, can_fit_shear: true },
      ],
    });
    expect(requiresAnalystShear(selection({ shearFitPolicies: ["redundant_boom"] }), single)).toBe(true);
  });

  it("is false for a policy that can fit shear", () => {
    expect(requiresAnalystShear(selection(), axes())).toBe(false);
  });

  it("does not demand an exponent for a policy that is unavailable anyway", () => {
    // `redundant_boom` here is unavailable, so the launch is blocked for that reason —
    // asking for a shear value on top would be a second, confusing complaint.
    const chosen = selection({ shearFitPolicies: ["redundant_boom"] });
    expect(requiresAnalystShear(chosen, axes())).toBe(false);
  });
});

describe("presets", () => {
  it("ties the two sensor axes together for Standard EYA", () => {
    const preset = SWEEP_PRESETS["Standard EYA"];
    expect(preset.shearFitPolicies).toEqual(preset.referencePolicies);
  });

  it("crosses them fully for Exhaustive", () => {
    const preset = SWEEP_PRESETS.Exhaustive;
    expect(preset.shearFitPolicies).toHaveLength(4);
    expect(preset.referencePolicies).toHaveLength(4);
  });

  it("keeps Quick look to a single leaf", () => {
    const preset = SWEEP_PRESETS["Quick look"];
    const leaves = [
      preset.shearFitPolicies,
      preset.referencePolicies,
      preset.shearModels,
      preset.referenceSources,
      preset.ltcAlgorithms,
    ].reduce((total, levels) => total * (levels?.length ?? 1), 1);
    expect(leaves).toBe(1);
  });
});

describe("store selection", () => {
  beforeEach(() => {
    useSweepStore.setState({ selection: selection(), filters: {}, rows: [] });
  });

  it("toggles a level on and off", () => {
    const { toggleLevel } = useSweepStore.getState();
    toggleLevel("ltcAlgorithms", "speedsort");
    expect(useSweepStore.getState().selection.ltcAlgorithms).toContain("speedsort");
    toggleLevel("ltcAlgorithms", "speedsort");
    expect(useSweepStore.getState().selection.ltcAlgorithms).not.toContain("speedsort");
  });

  it("applies a preset over the current selection", () => {
    useSweepStore.getState().applyPreset("Quick look");
    expect(useSweepStore.getState().selection.referenceSources).toEqual(["era5"]);
  });

  it("ignores an unknown preset rather than clearing the selection", () => {
    useSweepStore.getState().applyPreset("Nonexistent");
    expect(useSweepStore.getState().selection.ltcAlgorithms).toEqual(["variance_ratio"]);
  });

  it("stores and clears axis filters", () => {
    const { setFilter, clearFilters } = useSweepStore.getState();
    setFilter("reference_source", ["merra2"]);
    expect(useSweepStore.getState().filters.reference_source).toEqual(["merra2"]);
    clearFilters();
    expect(useSweepStore.getState().filters).toEqual({});
  });

  it("resets run state without losing the designed selection", () => {
    useSweepStore.setState({ phase: "complete", rows: [{ config_hash: "a" } as never] });
    useSweepStore.getState().reset();
    const state = useSweepStore.getState();
    expect(state.phase).toBe("idle");
    expect(state.rows).toEqual([]);
    expect(state.selection.ltcAlgorithms).toEqual(["variance_ratio"]);
  });
});
