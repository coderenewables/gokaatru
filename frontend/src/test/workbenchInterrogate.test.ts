import { afterEach, describe, expect, it } from "vitest";

import {
  MAX_PINNED,
  NO_TERMS,
  type SweepRow,
  type Terms,
  describeTerms,
  filterRows,
  hashesOf,
  levelsOf,
  metricsPresent,
  useInterrogate,
  withRange,
} from "../workbench/interrogate/store";
import { binCounts } from "../workbench/interrogate/DistributionPanel";

function row(
  hash: string,
  shear: string,
  source: string,
  speed: number | null,
  admissible = true,
  extra: Partial<SweepRow> = {},
): SweepRow {
  return {
    config_hash: hash,
    status: speed === null ? "failed" : "ok",
    admissible,
    shear_fit_policy: "all",
    reference_policy: "top",
    shear_model: shear,
    reference_source: source,
    ltc_algorithm: "linear",
    long_term_mean_speed_mps: speed,
    total_uncertainty_pct: speed === null ? null : 10 - speed / 2,
    capacity_factor: null,
    ...extra,
  };
}

const ROWS: SweepRow[] = [
  row("a", "power_law", "era5", 6.0),
  row("b", "power_law", "era5", 6.4),
  row("c", "power_law", "merra2", 7.2),
  row("d", "log_law", "era5", 7.6),
  row("e", "log_law", "merra2", 8.4),
  row("f", "log_law", "merra2", 9.0, false),
  row("g", "log_law", "era5", null, false),
];
const terms = (over: Partial<Terms> = {}): Terms => ({ ...NO_TERMS, ...over });
const hashes = (over: Partial<Terms> = {}, except?: "distribution") => hashesOf(filterRows(ROWS, terms(over), except));

describe("the scenarios the terms let through", () => {
  it("hides the inadmissible scenarios until asked", () => {
    expect(hashes()).toEqual(["a", "b", "c", "d", "e"]);
    expect(hashes({ showInadmissible: true })).toEqual(["a", "b", "c", "d", "e", "f", "g"]);
  });

  it("keeps the rows inside the distribution's range, bounds included", () => {
    expect(hashes({ distribution: [{ min: 6.4, max: 7.6 }] })).toEqual(["b", "c", "d"]);
  });

  it("reads the distribution's range on the chosen metric, and never keeps a missing value", () => {
    expect(hashes({ metric: "total_uncertainty_pct", distribution: [{ min: 6, max: 6.5 }], showInadmissible: true })).toEqual(["c", "d"]);
    expect(hashes({ distribution: [{ min: -1e9, max: 1e9 }], showInadmissible: true })).not.toContain("g");
  });

  it("takes a Shift-added range as a union within the one term", () => {
    const ranges = withRange(withRange([], { min: 6, max: 6.1 }, false), { min: 8, max: 9 }, true);
    expect(ranges).toHaveLength(2);
    expect(hashes({ distribution: ranges })).toEqual(["a", "e"]);
    expect(withRange(ranges, { min: 7, max: 7.3 }, false)).toEqual([{ min: 7, max: 7.3 }]);
  });

  it("filters by levels kept per axis", () => {
    expect(hashes({ levels: { shear_model: ["log_law"] } })).toEqual(["d", "e"]);
    expect(hashes({ levels: { shear_model: ["log_law"], reference_source: ["era5"] } })).toEqual(["d"]);
    expect(hashes({ levels: { shear_model: [] } })).toEqual([]);
  });

  it("filters by the parallel coordinates' level picks and numeric brushes", () => {
    expect(hashes({ picked: { reference_source: ["merra2"] } })).toEqual(["c", "e"]);
    expect(hashes({ ranges: { total_uncertainty_pct: [{ min: 6, max: 6.8 }] } })).toEqual(["b", "c", "d"]);
    expect(hashes({ ranges: { long_term_mean_speed_mps: [{ min: 6, max: 6.4 }, { min: 8, max: 9 }] } })).toEqual(["a", "b", "e"]);
  });

  it("intersects every term", () => {
    const all = terms({
      distribution: [{ min: 6, max: 8 }],
      picked: { reference_source: ["era5"] },
      levels: { shear_model: ["power_law", "log_law"] },
      ranges: { long_term_mean_speed_mps: [{ min: 6.2, max: 9 }] },
    });
    expect(hashesOf(filterRows(ROWS, all))).toEqual(["b", "d"]);
  });

  it("leaves a view's own term out for the context it draws", () => {
    const own = terms({ distribution: [{ min: 6, max: 6.5 }], levels: { shear_model: ["power_law"] } });
    expect(hashesOf(filterRows(ROWS, own))).toEqual(["a", "b"]);
    expect(hashesOf(filterRows(ROWS, own, "distribution"))).toEqual(["a", "b", "c"]);
  });
});

describe("what the terms are called", () => {
  it("lists each term in force, with an id to remove it by", () => {
    const chips = describeTerms(
      terms({
        distribution: [{ min: 6, max: 7 }],
        levels: { shear_model: ["log_law"] },
        picked: { reference_source: ["era5", "merra2"] },
        ranges: { total_uncertainty_pct: [{ min: 5, max: 6 }] },
      }),
    );
    expect(chips.map((chip) => chip.id)).toEqual(["distribution", "range:total_uncertainty_pct", "picked:reference_source", "levels:shear_model"]);
    expect(chips[0].text).toBe("Long-term mean speed 6 to 7");
    expect(describeTerms(NO_TERMS)).toEqual([]);
  });

  it("finds the levels and the metrics that hold a number", () => {
    expect(levelsOf(ROWS, "shear_model")).toEqual(["log_law", "power_law"]);
    expect(metricsPresent(ROWS)).toEqual(["long_term_mean_speed_mps", "total_uncertainty_pct"]);
  });
});

describe("the store", () => {
  afterEach(() => useInterrogate.getState().reset());

  it("pins at most two scenarios and refuses a third", () => {
    const store = useInterrogate.getState();
    expect(store.pin("a")).toBe(true);
    expect(useInterrogate.getState().pin("b")).toBe(true);
    expect(useInterrogate.getState().pin("c")).toBe(false);
    expect(useInterrogate.getState().pinned).toEqual(["a", "b"]);
    expect(MAX_PINNED).toBe(2);
    expect(useInterrogate.getState().pin("a")).toBe(true);
    expect(useInterrogate.getState().pinned).toEqual(["a", "b"]);
    useInterrogate.getState().unpin("a");
    expect(useInterrogate.getState().pin("c")).toBe(true);
    expect(useInterrogate.getState().pinned).toEqual(["b", "c"]);
  });

  it("drops the distribution's range when the metric changes, and a new sweep starts clean", () => {
    useInterrogate.getState().openSweep("s1");
    useInterrogate.getState().brushDistribution({ min: 1, max: 2 });
    useInterrogate.getState().setMetric("total_uncertainty_pct");
    expect(useInterrogate.getState().distribution).toEqual([]);
    useInterrogate.getState().brushLevels("shear_model", ["log_law"]);
    useInterrogate.getState().pin("a");
    useInterrogate.getState().openSweep("s2");
    const state = useInterrogate.getState();
    expect([state.sweepId, state.picked, state.pinned]).toEqual(["s2", {}, []]);
  });

  it("toggles a level off and back, dropping the filter once every level is kept again", () => {
    const all = ["log_law", "power_law"];
    useInterrogate.getState().toggleLevel("shear_model", "log_law", all);
    expect(useInterrogate.getState().levels).toEqual({ shear_model: ["power_law"] });
    useInterrogate.getState().toggleLevel("shear_model", "log_law", all);
    expect(useInterrogate.getState().levels).toEqual({});
  });

  it("removes a term by its chip id and clears every term at once", () => {
    const store = useInterrogate.getState();
    store.brushDistribution({ min: 1, max: 2 });
    store.brushRange("total_uncertainty_pct", { min: 1, max: 2 });
    store.brushLevels("reference_source", ["era5"]);
    useInterrogate.getState().removeTerm("range:total_uncertainty_pct");
    expect(describeTerms(useInterrogate.getState()).map((chip) => chip.id)).toEqual(["distribution", "picked:reference_source"]);
    useInterrogate.getState().clearAll();
    expect(describeTerms(useInterrogate.getState())).toEqual([]);
  });

  it("exposes the filtered config hashes for the panels built on it", () => {
    useInterrogate.getState().setRows(ROWS);
    useInterrogate.getState().brushLevels("shear_model", ["log_law"]);
    const state = useInterrogate.getState();
    expect(hashesOf(filterRows(state.rows, state))).toEqual(["d", "e"]);
  });
});

describe("the histogram's bins", () => {
  it("counts every value once, the top value in the last bin", () => {
    const counts = binCounts([0, 1, 2, 3, 4, 10], 0, 10, 5);
    expect(counts).toEqual([2, 2, 1, 0, 1]);
    expect(counts.reduce((a, b) => a + b, 0)).toBe(6);
    expect(binCounts([5, 5], 5, 5, 4)).toEqual([2, 0, 0, 0]);
  });
});
