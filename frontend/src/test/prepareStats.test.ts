import { describe, expect, it } from "vitest";

import { meanCoverage } from "../lib/prepareStats";
import type { SensorRow } from "../types/analysis";

function sensor(overrides: Partial<SensorRow> = {}): SensorRow {
  return {
    name: "Spd_80m",
    height_m: 80,
    sensor_type: "wind_speed",
    data_coverage_pct: 95,
    record_count: 1000,
    ...overrides,
  };
}

describe("meanCoverage", () => {
  it("returns the arithmetic mean of data_coverage_pct across sensors", () => {
    const sensors = [sensor({ data_coverage_pct: 90 }), sensor({ data_coverage_pct: 100 })];
    expect(meanCoverage(sensors)).toBe(95);
  });

  it("returns null for an empty sensor list rather than NaN or 0", () => {
    expect(meanCoverage([])).toBeNull();
  });

  it("ignores dropped sensors when a drop-filter set is given", () => {
    const sensors = [
      sensor({ name: "Spd_80m", data_coverage_pct: 90 }),
      sensor({ name: "Spd_40m", data_coverage_pct: 10 }),
    ];
    expect(meanCoverage(sensors, new Set(["Spd_40m"]))).toBe(90);
  });
});
