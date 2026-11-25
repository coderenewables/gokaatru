import { tableFromIPC } from "apache-arrow";

import type { Definition, Polygon } from "../selection/store";
import { axisRange as axisRangeOf, toNormalised, type Range } from "./geometry";

export interface HighlightMeta {
  name?: string;
  inline?: string;
  records: number;
  of_records: number;
  basis?: string;
}

export interface PairsMeta {
  x_channel: string;
  y_channel: string;
  window_records: number;
  records: number;
  highlight?: HighlightMeta | null;
}

export interface Pairs {
  x: Float64Array;
  y: Float64Array;
  /** null when the request carried no selection. */
  highlighted: Uint8Array | null;
  meta: PairsMeta;
}

/** The server's pairs stream: ``time``, ``x``, ``y`` and, with a selection, ``highlighted``. */
export function decodePairs(buffer: ArrayBuffer | Uint8Array): Pairs {
  const table = tableFromIPC(buffer);
  const raw = table.schema.metadata.get("gokaatru");
  if (raw === undefined) throw new Error("The pairs stream carries no metadata");
  const meta = JSON.parse(raw) as PairsMeta;
  const x = Float64Array.from(table.getChild("x")?.toArray() ?? []);
  const y = Float64Array.from(table.getChild("y")?.toArray() ?? []);
  const flag = table.getChild("highlighted");
  let highlighted: Uint8Array | null = null;
  if (flag) {
    highlighted = new Uint8Array(table.numRows);
    for (let i = 0; i < highlighted.length; i += 1) highlighted[i] = flag.get(i) ? 1 : 0;
  }
  return { x, y, highlighted, meta };
}

export interface PlotPoints {
  x: Float32Array;
  y: Float32Array;
  /** 0 muted, 1 highlighted. */
  category: Float32Array;
}

/** The points in the normalised coordinates regl-scatterplot draws, highlighted ones last
 * so they sit on top of the muted ones. */
export function plotPoints(pairs: Pairs, xRange: Range, yRange: Range): PlotPoints {
  const count = pairs.x.length;
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const category = new Float32Array(count);
  let at = 0;
  const put = (i: number, mark: number) => {
    x[at] = toNormalised(pairs.x[i], xRange);
    y[at] = toNormalised(pairs.y[i], yRange);
    category[at] = mark;
    at += 1;
  };
  const flags = pairs.highlighted;
  for (let i = 0; i < count; i += 1) if (!flags || !flags[i]) put(i, 0);
  if (flags) for (let i = 0; i < count; i += 1) if (flags[i]) put(i, 1);
  return { x, y, category };
}

/** Every polygon of a view's term (a union holds one per Shift-lasso) on these channels. */
export function polygonsOf(term: Definition | undefined, xChannel: string, yChannel: string): Polygon[] {
  if (!term) return [];
  if (term.kind === "polygon") {
    return term.x_channel === xChannel && term.y_channel === yChannel ? [term] : [];
  }
  if (term.kind === "union" || term.kind === "intersection") {
    return term.of.flatMap((part) => polygonsOf(part, xChannel, yChannel));
  }
  return [];
}

/** The axis ranges the pairs need: speeds share one range, so the 1:1 diagonal runs corner
 * to corner; any other pair of channels takes a range each. */
export function rangesFor(pairs: Pairs, shared: boolean): { x: Range; y: Range } {
  const span = (values: Float64Array) => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const value of values) {
      if (value < lo) lo = value;
      if (value > hi) hi = value;
    }
    return lo > hi ? { lo: 0, hi: 1 } : { lo, hi };
  };
  const xs = span(pairs.x);
  const ys = span(pairs.y);
  if (shared) {
    const both = axisRangeOf(Math.min(xs.lo, ys.lo), Math.max(xs.hi, ys.hi));
    return { x: both, y: both };
  }
  return { x: axisRangeOf(xs.lo, xs.hi), y: axisRangeOf(ys.lo, ys.hi) };
}
