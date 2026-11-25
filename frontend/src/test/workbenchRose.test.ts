import { describe, expect, it } from "vitest";

import { LABELS, bearingOf, sectorOf, sectorTerm, sectorsOf, termOf, toggled, wedge } from "../workbench/rose/geometry";
import { defaultChannels } from "../workbench/rose/RosePanel";

describe("the rose's sectors", () => {
  it("are binned as compute_windrose_data bins them, centred on north, half-open", () => {
    expect(sectorTerm(0, "Dir_100m")).toEqual({ kind: "sector", channel: "Dir_100m", from_deg: 345, to_deg: 15 });
    expect(sectorTerm(3, "Dir_100m")).toEqual({ kind: "sector", channel: "Dir_100m", from_deg: 75, to_deg: 105 });
    expect(sectorTerm(11, "Dir_100m")).toEqual({ kind: "sector", channel: "Dir_100m", from_deg: 315, to_deg: 345 });
    expect([0, 14.999, 15, 344.999, 345, 359.9, 360].map(sectorOf)).toEqual([0, 0, 1, 11, 0, 0, 0]);
    expect(LABELS).toEqual(["N", "30°", "60°", "E", "120°", "150°", "S", "210°", "240°", "W", "300°", "330°"]);
  });

  it("reads a pointer's bearing clockwise from north with the screen's y down", () => {
    expect(bearingOf(0, -10)).toBeCloseTo(0);
    expect(bearingOf(10, 0)).toBeCloseTo(90);
    expect(bearingOf(0, 10)).toBeCloseTo(180);
    expect(bearingOf(-10, 0)).toBeCloseTo(270);
  });

  it("toggles a click alone, adds or removes with Shift, and clears the only one", () => {
    expect(toggled([], 2, false)).toEqual([2]);
    expect(toggled([2], 5, false)).toEqual([5]);
    expect(toggled([2], 5, true)).toEqual([2, 5]);
    expect(toggled([2, 5], 2, true)).toEqual([5]);
    expect(toggled([2, 5], 2, false)).toEqual([2]);
    expect(toggled([2], 2, false)).toEqual([]);
  });

  it("round-trips sectors through the term the crossfilter holds", () => {
    expect(termOf([], "Dir_100m")).toBeNull();
    expect(termOf([0], "Dir_100m")).toEqual(sectorTerm(0, "Dir_100m"));
    const union = termOf([0, 3, 9], "Dir_100m");
    expect(union).toEqual({ kind: "union", of: [0, 3, 9].map((k) => sectorTerm(k, "Dir_100m")) });
    expect(sectorsOf(union ?? undefined, "Dir_100m")).toEqual([0, 3, 9]);
    expect(sectorsOf(union ?? undefined, "Dir_80m")).toEqual([]);
    expect(sectorsOf({ kind: "sector", channel: "Dir_100m", from_deg: 10, to_deg: 50 }, "Dir_100m")).toEqual([]);
  });

  it("draws a wedge only when it has a radius", () => {
    expect(wedge(0, 0)).toBe("");
    expect(wedge(0, 100)).toMatch(/^M0 0L-25\.88 -96\.59A100\.00 100\.00 0 0 1 25\.88 -96\.59Z$/);
  });

  it("reads the highest vane and the cup beside it", () => {
    const instrument = (name: string, type: string, height: number, inData = true) => ({
      name, sensor_type: type, height_m: height, in_data: inData, mapped_as: null, statistics: [],
    });
    expect(
      defaultChannels([
        instrument("Dir_120m", "wind_direction", 120, false),
        instrument("Spd_100m", "wind_speed", 100),
        instrument("Dir_80m", "wind_direction", 80),
        instrument("Spd_80m", "wind_speed", 80),
      ]),
    ).toEqual({ direction: "Dir_80m", speed: "Spd_80m" });
    expect(defaultChannels([instrument("Spd_100m", "wind_speed", 100)])).toEqual({ direction: null, speed: "Spd_100m" });
  });
});
