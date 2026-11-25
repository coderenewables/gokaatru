import type { Table } from "apache-arrow";

import type { FlagInterval } from "../flags/store";
import type { Definition } from "../selection/store";

// The pure parts of the timeline: Arrow table to uPlot arrays, pixels to times, the term as
// shaded ranges, a flag interval as a band. Nothing here touches the DOM or uPlot, so each is
// tested on its own (src/test/workbenchTimeline.test.ts).

/** The record step assumed for the band of a flag on the last record, which has no ``next``. */
export const DEFAULT_STEP_MS = 10 * 60 * 1000;
/** A drag shorter than this many pixels is a click. */
export const CLICK_PIXELS = 3;
/** The narrowest window a zoom reaches. */
export const MIN_WINDOW_MS = 60 * 60 * 1000;

export interface WindowMeta {
  channels: string[];
  start_ms: number;
  end_ms: number;
  records: number;
  decimated: boolean;
  bucket_ms: number;
}

export interface SeriesWindow {
  meta: WindowMeta;
  /** Seconds, as uPlot's time scale reads them. */
  times: number[];
  /** Per channel, in ``meta.channels`` order: the bucket minimum and maximum, null where empty. */
  envelopes: { min: (number | null)[]; max: (number | null)[] }[];
}

const finite = (value: unknown): number | null => {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

export function parseWindow(table: Table): SeriesWindow {
  const raw = table.schema.metadata.get("gokaatru");
  if (raw === undefined) throw new Error("The series response carries no window description");
  const meta = JSON.parse(raw) as WindowMeta;
  const time = table.getChild("time");
  if (time === null) throw new Error("The series response has no time column");
  const times: number[] = [];
  for (let row = 0; row < table.numRows; row += 1) times.push(Number(time.get(row)) / 1000);
  const column = (name: string): (number | null)[] => {
    const child = table.getChild(name);
    if (child === null) throw new Error(`The series response has no ${name} column`);
    const values: (number | null)[] = [];
    for (let row = 0; row < table.numRows; row += 1) values.push(finite(child.get(row)));
    return values;
  };
  return {
    meta,
    times,
    envelopes: meta.channels.map((channel) => ({ min: column(`${channel}.min`), max: column(`${channel}.max`) })),
  };
}

/** uPlot's data: the times, then each channel's minimum and maximum. */
export function plotData(window: SeriesWindow): (number | null)[][] {
  return [window.times, ...window.envelopes.flatMap((envelope) => [envelope.min, envelope.max])];
}

/** The pixel offset in the plot to a time. */
export function pixelToMs(pixel: number, plotWidth: number, minMs: number, maxMs: number): number {
  return minMs + (pixel / plotWidth) * (maxMs - minMs);
}

export function msToPixel(ms: number, plotWidth: number, minMs: number, maxMs: number): number {
  return ((ms - minMs) / (maxMs - minMs)) * plotWidth;
}

const wholeSecond = (ms: number) => Math.round(ms / 1000) * 1000;

/** The period a brush from ``left`` across ``width`` pixels draws, as the term's bounds. */
export function brushTerm(left: number, width: number, plotWidth: number, minMs: number, maxMs: number): Definition {
  return {
    kind: "time_range",
    start: new Date(wholeSecond(pixelToMs(left, plotWidth, minMs, maxMs))).toISOString(),
    end: new Date(wholeSecond(pixelToMs(left + width, plotWidth, minMs, maxMs))).toISOString(),
  };
}

/** The x ranges, in ms, a timeline term shades: one per period of a union; an unbounded side
 * is open-ended. Terms of other kinds are not the timeline's and shade nothing. */
export function termRanges(term: Definition | undefined): [number, number][] {
  if (term === undefined) return [];
  if (term.kind === "union") return term.of.flatMap((part) => termRanges(part));
  if (term.kind !== "time_range") return [];
  const start = term.start ? Date.parse(term.start) : -Infinity;
  const end = term.end ? Date.parse(term.end) : Infinity;
  return Number.isNaN(start) || Number.isNaN(end) || end <= start ? [] : [[start, end]];
}

/** The window enclosing every range, or null when the term has none or one side is open. */
export function termExtent(ranges: [number, number][]): [number, number] | null {
  if (ranges.length === 0) return null;
  const start = Math.min(...ranges.map(([from]) => from));
  const end = Math.max(...ranges.map(([, to]) => to));
  return Number.isFinite(start) && Number.isFinite(end) ? [start, end] : null;
}

/** The window after a wheel step: ``factor`` below 1 zooms in, around the cursor at ``anchor``
 * (0 to 1 across the plot), within the record's extent and not narrower than MIN_WINDOW_MS. */
export function zoomWindow(
  minMs: number,
  maxMs: number,
  anchor: number,
  factor: number,
  extent: [number, number],
): [number, number] {
  const span = Math.min(Math.max((maxMs - minMs) * factor, MIN_WINDOW_MS), extent[1] - extent[0]);
  const centre = minMs + anchor * (maxMs - minMs);
  let start = centre - anchor * span;
  start = Math.min(Math.max(start, extent[0]), extent[1] - span);
  return [start, start + span];
}

export interface FlagBand {
  sensor: string;
  interval: FlagInterval;
  /** [start, end) in ms. */
  start: number;
  end: number;
}

/** A flagged run as the band it paints: from its first record to the next one's, or past the
 * last by one step when it ends the record. */
export function flagBand(sensor: string, interval: FlagInterval, stepMs = DEFAULT_STEP_MS): FlagBand {
  const start = Date.parse(interval.first);
  const end = interval.next !== null ? Date.parse(interval.next) : Date.parse(interval.last) + stepMs;
  return { sensor, interval, start, end };
}

/** The band under a time, the latest drawn when several overlap. */
export function bandAt(bands: FlagBand[], ms: number): FlagBand | null {
  for (let at = bands.length - 1; at >= 0; at -= 1) {
    if (ms >= bands[at].start && ms < bands[at].end) return bands[at];
  }
  return null;
}

const utc = (value: string) => new Date(value).toISOString().slice(0, 16).replace("T", " ");

/** What a click on a band announces: the channel, the run, how many records, why and who. */
export function flagLine(band: FlagBand): string {
  const { interval } = band;
  return (
    `${band.sensor} flagged ${utc(interval.first)} to ${utc(interval.last)} UTC, ${interval.records} records, ` +
    `${interval.reason}, ${interval.rule_type}, by ${interval.actor}`
  );
}

/** "#rrggbb" or "rgb(r, g, b)" with an alpha, for the envelope fill. */
export function withAlpha(colour: string, alpha: number): string {
  const text = colour.trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(text);
  if (hex) {
    const value = parseInt(hex[1], 16);
    return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
  }
  const channels = /^rgba?\(([^)]+)\)/.exec(text);
  if (channels) {
    const [r, g, b] = channels[1].split(",").map((part) => part.trim());
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return text;
}
