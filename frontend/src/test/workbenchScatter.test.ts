import { Bool, Float64, Schema, Table, tableFromArrays, tableToIPC, vectorFromArray } from "apache-arrow";
import { describe, expect, it } from "vitest";

import {
  axisRange,
  fromNormalised,
  fromScreen,
  lassoPolygon,
  MAX_LASSO_VERTICES,
  signedArea,
  simplifyRing,
  ticks,
  toNormalised,
  toScreenX,
  toScreenY,
  type Vertex,
} from "../workbench/scatter/geometry";
import { decodePairs, plotPoints, polygonsOf, rangesFor } from "../workbench/scatter/pairs";

const box = { width: 400, height: 300 };
const x = { lo: 0, hi: 20 };
const y = { lo: -10, hi: 20 };

describe("scatter geometry", () => {
  it("rounds a range up to a tick and keeps zero as the floor", () => {
    expect(axisRange(0.3, 17.2)).toEqual({ lo: 0, hi: 18 });
    expect(axisRange(-3.2, 5)).toEqual({ lo: -4, hi: 5 });
    expect(ticks({ lo: 0, hi: 20 }, 4)).toEqual([0, 5, 10, 15, 20]);
  });

  it("maps data to normalised coordinates and back", () => {
    expect(toNormalised(0, x)).toBe(-1);
    expect(toNormalised(20, x)).toBe(1);
    expect(toNormalised(5, y)).toBeCloseTo(0.0, 12);
    for (const value of [-10, -3.3, 0, 7.77, 20]) expect(fromNormalised(toNormalised(value, y), y)).toBeCloseTo(value, 12);
  });

  it("maps data to screen with y upwards and back through fromScreen", () => {
    expect(toScreenX(10, x, box)).toBe(200);
    expect(toScreenY(20, y, box)).toBe(0);
    expect(toScreenY(-10, y, box)).toBe(300);
    for (const point of [[0, 0], [7.5, 12.25], [20, -10]] as Vertex[]) {
      const screen: Vertex = [toScreenX(point[0], x, box), toScreenY(point[1], y, box)];
      const back = fromScreen(screen, x, y, box);
      expect(back[0]).toBeCloseTo(point[0], 10);
      expect(back[1]).toBeCloseTo(point[1], 10);
    }
  });
});

describe("the lasso", () => {
  const circle = (count: number, radius = 80): Vertex[] =>
    Array.from({ length: count }, (_, i) => [200 + radius * Math.cos((2 * Math.PI * i) / count), 150 + radius * Math.sin((2 * Math.PI * i) / count)]);

  it("converts a screen path to a data polygon", () => {
    const polygon = lassoPolygon([[100, 150], [300, 150], [300, 300], [100, 300]], x, y, box);
    expect(polygon).toEqual([[5, 5], [15, 5], [15, -10], [5, -10]]);
  });

  it("keeps at most 200 vertices of a long path and the shape's area", () => {
    const path = circle(2500);
    const ring = simplifyRing(path);
    expect(ring.length).toBeLessThanOrEqual(MAX_LASSO_VERTICES);
    expect(ring.length).toBeGreaterThanOrEqual(3);
    expect(Math.abs(signedArea(ring)) / Math.abs(signedArea(path))).toBeGreaterThan(0.99);
    const polygon = lassoPolygon(path, x, y, box);
    expect(polygon).not.toBeNull();
    expect(polygon!.length).toBeLessThanOrEqual(MAX_LASSO_VERTICES);
  });

  it("drops a repeated closing vertex and never goes below three", () => {
    const square: Vertex[] = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
    expect(simplifyRing(square)).toHaveLength(4);
    expect(simplifyRing(circle(50), 1)).toHaveLength(3);
    expect(Math.abs(signedArea(simplifyRing(circle(50), 1)))).toBeGreaterThan(0);
  });

  it("refuses a click, a line and a path with too few points", () => {
    expect(lassoPolygon([[10, 10], [11, 10], [10, 11]], x, y, box)).toBeNull();
    expect(lassoPolygon([[10, 10], [100, 100], [200, 200], [50, 50]], x, y, box)).toBeNull();
    expect(lassoPolygon([[10, 10], [100, 100]], x, y, box)).toBeNull();
  });
});

describe("pairs", () => {
  function stream(withHighlight: boolean): Uint8Array {
    const columns: Record<string, unknown> = {
      time: vectorFromArray([1, 2, 3], new Float64()),
      x: vectorFromArray([1, 5, 9], new Float64()),
      y: vectorFromArray([2, 6, 0.4], new Float64()),
    };
    if (withHighlight) columns.highlighted = vectorFromArray([false, false, true], new Bool());
    const table = tableFromArrays(columns as never) as unknown as Table;
    const meta = new Map([["gokaatru", JSON.stringify({
      x_channel: "a", y_channel: "b", start_ms: 0, end_ms: 9, window_records: 5, records: 3,
      ...(withHighlight ? { highlight: { name: "", inline: "{}", records: 1, of_records: 5, basis: "x" } } : {}),
    })]]);
    return tableToIPC(new Table(new Schema(table.schema.fields, meta), table.batches as never));
  }

  it("decodes columns and metadata, with and without a highlight", () => {
    const plain = decodePairs(stream(false));
    expect(Array.from(plain.x)).toEqual([1, 5, 9]);
    expect(plain.highlighted).toBeNull();
    expect(plain.meta.records).toBe(3);
    expect(plain.meta.window_records).toBe(5);
    const marked = decodePairs(stream(true));
    expect(Array.from(marked.highlighted!)).toEqual([0, 0, 1]);
    expect(marked.meta.highlight?.records).toBe(1);
  });

  it("puts highlighted points last, in normalised units, and shares one range for speeds", () => {
    const pairs = decodePairs(stream(true));
    const ranges = rangesFor(pairs, true);
    expect(ranges.x).toEqual(ranges.y);
    const points = plotPoints(pairs, ranges.x, ranges.y);
    expect(Array.from(points.category)).toEqual([0, 0, 1]);
    expect(points.x[2]).toBeCloseTo(toNormalised(9, ranges.x), 6);
    expect(points.y[2]).toBeCloseTo(toNormalised(0.4, ranges.y), 6);
  });

  it("lists a term's polygons on the drawn channels only", () => {
    const polygon = { kind: "polygon" as const, x_channel: "a", y_channel: "b", vertices: [[0, 0], [1, 0], [1, 1]] as Vertex[] };
    const other = { ...polygon, x_channel: "c" };
    expect(polygonsOf({ kind: "union", of: [polygon, other, polygon] }, "a", "b")).toHaveLength(2);
    expect(polygonsOf(undefined, "a", "b")).toEqual([]);
  });
});
