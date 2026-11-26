import { Float64, Schema, Table, TimestampMillisecond, tableFromArrays, vectorFromArray, type Field } from "apache-arrow";
import { describe, expect, it } from "vitest";

import type { FlagInterval } from "../workbench/flags/store";
import {
  bandAt,
  brushTerm,
  flagBand,
  flagLine,
  msToPixel,
  parseWindow,
  pixelToMs,
  plotData,
  termExtent,
  termRanges,
  withAlpha,
  zoomWindow,
} from "../workbench/timeline/helpers";

const T0 = Date.UTC(2023, 2, 1);

function windowTable(): Table {
  const times = vectorFromArray([T0, T0 + 600000, T0 + 1200000], new TimestampMillisecond());
  const base = new Table({
    time: times,
    "A.min": vectorFromArray([1, NaN, 3], new Float64()),
    "A.max": vectorFromArray([2, NaN, 4], new Float64()),
  });
  const meta = { channels: ["A"], start_ms: T0, end_ms: T0 + 1800000, records: 3, decimated: false, bucket_ms: 600000 };
  const schema = new Schema(base.schema.fields as Field[], new Map([["gokaatru", JSON.stringify(meta)]]));
  return new Table(schema, base.batches);
}

const interval = (patch: Partial<FlagInterval> = {}): FlagInterval => ({
  first: "2023-03-14T21:20:00Z",
  last: "2023-03-15T05:10:00Z",
  next: "2023-03-15T05:20:00Z",
  records: 48,
  rule_sequence: 1,
  rule_type: "custom_period_exclude",
  reason: "excluded_period",
  actor: "user",
  flagged_at: "2026-11-25T10:00:00Z",
  ...patch,
});

describe("series window", () => {
  it("turns an Arrow table into uPlot arrays, empty buckets as null, times in seconds", () => {
    const window = parseWindow(windowTable());
    expect(window.meta.channels).toEqual(["A"]);
    expect(plotData(window)).toEqual([
      [T0 / 1000, T0 / 1000 + 600, T0 / 1000 + 1200],
      [1, null, 3],
      [2, null, 4],
    ]);
  });

  it("refuses a table without the window description", () => {
    expect(() => parseWindow(tableFromArrays({ time: [1] }))).toThrow(/window description/);
  });
});

describe("brush", () => {
  it("converts pixels to times and back", () => {
    expect(pixelToMs(250, 1000, 0, 4000)).toBe(1000);
    expect(msToPixel(1000, 1000, 0, 4000)).toBe(250);
  });

  it("makes a half-open UTC term from the dragged pixels", () => {
    const term = brushTerm(100, 200, 1000, T0, T0 + 10 * 3600000);
    expect(term).toEqual({ kind: "time_range", start: "2023-03-01T01:00:00.000Z", end: "2023-03-01T03:00:00.000Z" });
  });
});

describe("shaded ranges", () => {
  it("lists each period of a union", () => {
    const term = {
      kind: "union" as const,
      of: [
        { kind: "time_range" as const, start: "2023-03-01T00:00:00Z", end: "2023-03-02T00:00:00Z" },
        { kind: "time_range" as const, start: "2023-03-05T00:00:00Z", end: "2023-03-06T00:00:00Z" },
      ],
    };
    const ranges = termRanges(term);
    expect(ranges).toHaveLength(2);
    expect(termExtent(ranges)).toEqual([Date.parse("2023-03-01T00:00:00Z"), Date.parse("2023-03-06T00:00:00Z")]);
  });

  it("leaves open sides open and ignores other kinds", () => {
    expect(termRanges({ kind: "time_range", start: "2023-03-01T00:00:00Z" })).toEqual([[T0, Infinity]]);
    expect(termExtent(termRanges({ kind: "time_range", start: "2023-03-01T00:00:00Z" }))).toBeNull();
    expect(termRanges({ kind: "band", channel: "A", min: 1 })).toEqual([]);
    expect(termRanges(undefined)).toEqual([]);
  });
});

describe("zoom", () => {
  it("zooms around the cursor and stays inside the record", () => {
    const extent: [number, number] = [0, 100 * 3600000];
    const [from, to] = zoomWindow(0, 100 * 3600000, 0.5, 0.5, extent);
    expect([from, to]).toEqual([25 * 3600000, 75 * 3600000]);
    expect(zoomWindow(0, 10 * 3600000, 0, 2, extent)).toEqual([0, 20 * 3600000]);
    const wide = zoomWindow(0, 100 * 3600000, 0.5, 4, extent);
    expect(wide).toEqual(extent);
  });

  it("does not go narrower than an hour", () => {
    const [from, to] = zoomWindow(0, 3600000, 0.5, 0.1, [0, 1e9]);
    expect(to - from).toBe(3600000);
  });
});

describe("flag bands", () => {
  it("spans [first, next)", () => {
    const band = flagBand("Spd_100m", interval());
    expect(band.start).toBe(Date.parse("2023-03-14T21:20:00Z"));
    expect(band.end).toBe(Date.parse("2023-03-15T05:20:00Z"));
    expect(bandAt([band], band.start)).toBe(band);
    expect(bandAt([band], band.end)).toBeNull();
  });

  it("runs a flag on the last record one step past it", () => {
    const band = flagBand("Spd_100m", interval({ next: null }), 600000);
    expect(band.end).toBe(Date.parse("2023-03-15T05:10:00Z") + 600000);
  });

  it("words a click for the live region", () => {
    expect(flagLine(flagBand("Spd_100m", interval()))).toBe(
      "Spd_100m flagged 2023-03-14 21:20 to 2023-03-15 05:10 UTC, 48 records, excluded_period, custom_period_exclude, by user",
    );
  });
});

describe("colour", () => {
  it("adds an alpha to hex and rgb colours", () => {
    expect(withAlpha("#151a21", 0.5)).toBe("rgba(21, 26, 33, 0.5)");
    expect(withAlpha("rgb(1, 2, 3)", 0.5)).toBe("rgba(1, 2, 3, 0.5)");
  });
});

