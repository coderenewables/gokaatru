import { useMemo } from "react";
import { create } from "zustand";

import { AXIS_COLUMNS, AXIS_LABELS, METRIC_COLUMNS, METRIC_META, type AxisColumn } from "../../types/sweep";

// Interrogate's crossfilter (decisions/0015.7), the scenario counterpart of Prepare's
// (selection/store.ts): each view holds its own term and the scenarios every panel shows are
// the intersection of them. The browser only keeps the bounds the analyst drew and which rows
// pass them; every number in a row was computed by the server.

export type SweepRow = Record<string, string | number | boolean | null | undefined> & {
  config_hash: string;
  admissible: boolean;
  status: string;
};

export interface Range {
  min: number;
  max: number;
}

/** How a missing axis value reads as a level. */
export const NO_LEVEL = "—";
export const MAX_PINNED = 2;
export const DEFAULT_METRIC = "long_term_mean_speed_mps";

/** The terms in force. A missing key is "not drawn"; an empty list never occurs for ranges. */
export interface Terms {
  metric: string;
  /** The distribution's brush: ranges of ``metric``, any of which keeps a row (Shift adds one). */
  distribution: Range[];
  /** Parallel coordinates, numeric axes: per metric, the ranges that keep a row. */
  ranges: Record<string, Range[]>;
  /** Parallel coordinates, categorical axes: per axis, the levels that keep a row. */
  picked: Record<string, string[]>;
  /** Level filters: per axis, the levels kept; an axis without an entry keeps every level. */
  levels: Record<string, string[]>;
  showInadmissible: boolean;
}

export const NO_TERMS: Terms = {
  metric: DEFAULT_METRIC,
  distribution: [],
  ranges: {},
  picked: {},
  levels: {},
  showInadmissible: false,
};

export function levelOf(row: SweepRow, axis: string): string {
  const value = row[axis];
  return value === null || value === undefined ? NO_LEVEL : String(value);
}

export function metricValue(row: SweepRow, column: string): number | null {
  const value = row[column];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function inAny(value: number | null, ranges: Range[]): boolean {
  return value !== null && ranges.some((range) => value >= range.min && value <= range.max);
}

/** What a view leaves out of the intersection: its own brush, which it draws its context from
 * (the rows that brush would otherwise hide), or the admissibility filter, for the gates panel,
 * whose subject is the scenarios the gates excluded. */
export type Except = "distribution" | "admissibility";

/** The rows every term lets through, but the one ``except`` names. */
export function filterRows(rows: readonly SweepRow[], terms: Terms, except?: Except): SweepRow[] {
  const numeric = Object.entries(terms.ranges).filter(([, ranges]) => ranges.length > 0);
  const categorical = Object.entries(terms.picked);
  const levels = Object.entries(terms.levels);
  return rows.filter((row) => {
    if (except !== "admissibility" && !terms.showInadmissible && !row.admissible) return false;
    for (const [axis, kept] of levels) if (!kept.includes(levelOf(row, axis))) return false;
    for (const [axis, kept] of categorical) if (!kept.includes(levelOf(row, axis))) return false;
    for (const [column, ranges] of numeric) if (!inAny(metricValue(row, column), ranges)) return false;
    if (except !== "distribution" && terms.distribution.length > 0) {
      if (!inAny(metricValue(row, terms.metric), terms.distribution)) return false;
    }
    return true;
  });
}

export function hashesOf(rows: readonly SweepRow[]): string[] {
  return rows.map((row) => row.config_hash);
}

/** The distinct levels of an axis in the rows, sorted, with the rows' own spelling. */
export function levelsOf(rows: readonly SweepRow[], axis: string): string[] {
  return [...new Set(rows.map((row) => levelOf(row, axis)))].sort();
}

/** Metric columns that hold a number in at least one row, in the server's order. */
export function metricsPresent(rows: readonly SweepRow[]): string[] {
  return METRIC_COLUMNS.filter((column) => rows.some((row) => metricValue(row, column) !== null));
}

export interface TermChip {
  /** The id ``removeTerm`` takes. */
  id: string;
  label: string;
  text: string;
}

const trim = (value: number) => Number(value.toPrecision(5)).toString();
const describeRange = (range: Range) => `${trim(range.min)} to ${trim(range.max)}`;

/** Every term in force, in words, for removable chips. */
export function describeTerms(terms: Terms): TermChip[] {
  const chips: TermChip[] = [];
  const label = (column: string) => METRIC_META[column as keyof typeof METRIC_META]?.label ?? column;
  if (terms.distribution.length > 0) {
    chips.push({
      id: "distribution",
      label: "Distribution",
      text: `${label(terms.metric)} ${terms.distribution.map(describeRange).join(" or ")}`,
    });
  }
  for (const [column, ranges] of Object.entries(terms.ranges)) {
    if (ranges.length > 0) {
      chips.push({ id: `range:${column}`, label: "Parallel", text: `${label(column)} ${ranges.map(describeRange).join(" or ")}` });
    }
  }
  const axisLabel = (axis: string) => AXIS_LABELS[axis as AxisColumn] ?? axis;
  for (const [axis, kept] of Object.entries(terms.picked)) {
    chips.push({ id: `picked:${axis}`, label: "Parallel", text: `${axisLabel(axis)} ${kept.length ? kept.join(", ") : "no level"}` });
  }
  for (const [axis, kept] of Object.entries(terms.levels)) {
    chips.push({ id: `levels:${axis}`, label: "Levels", text: `${axisLabel(axis)} ${kept.length ? kept.join(", ") : "no level"}` });
  }
  return chips;
}

/** Shift adds a range to a view's own term rather than replacing it. */
export function withRange(current: Range[], range: Range, extend: boolean): Range[] {
  return extend ? [...current, range] : [range];
}

export function withLevels(current: string[] | undefined, picked: string[], extend: boolean): string[] {
  return extend && current ? [...new Set([...current, ...picked])] : picked;
}

interface InterrogateStore extends Terms {
  sweepId: string | null;
  rows: SweepRow[];
  pinned: string[];
  openSweep: (id: string | null) => void;
  setRows: (rows: SweepRow[]) => void;
  setMetric: (metric: string) => void;
  setShowInadmissible: (show: boolean) => void;
  brushDistribution: (range: Range, extend?: boolean) => void;
  brushRange: (column: string, range: Range, extend?: boolean) => void;
  brushLevels: (axis: string, levels: string[], extend?: boolean) => void;
  /** Keep or drop one level of an axis; ``all`` is the axis's levels, for the first drop. */
  toggleLevel: (axis: string, level: string, all: string[]) => void;
  removeTerm: (id: string) => void;
  clearDistribution: () => void;
  clearParallel: () => void;
  clearAll: () => void;
  /** False, and nothing pinned, when two are already (a third is refused, not swapped in). */
  pin: (hash: string) => boolean;
  unpin: (hash: string) => void;
  reset: () => void;
}

const FRESH = { ...NO_TERMS, sweepId: null, rows: [] as SweepRow[], pinned: [] as string[] };

export const useInterrogate = create<InterrogateStore>((set, get) => ({
  ...FRESH,
  openSweep: (id) => set((state) => (state.sweepId === id ? state : { ...FRESH, sweepId: id })),
  setRows: (rows) => set({ rows }),
  // A range of one metric means nothing on another.
  setMetric: (metric) => set((state) => (state.metric === metric ? state : { metric, distribution: [] })),
  setShowInadmissible: (showInadmissible) => set({ showInadmissible }),
  brushDistribution: (range, extend = false) =>
    set((state) => ({ distribution: withRange(state.distribution, range, extend) })),
  brushRange: (column, range, extend = false) =>
    set((state) => ({ ranges: { ...state.ranges, [column]: withRange(state.ranges[column] ?? [], range, extend) } })),
  brushLevels: (axis, levels, extend = false) =>
    set((state) => ({ picked: { ...state.picked, [axis]: withLevels(state.picked[axis], levels, extend) } })),
  toggleLevel: (axis, level, all) =>
    set((state) => {
      const kept = state.levels[axis] ?? all;
      const next = kept.includes(level) ? kept.filter((item) => item !== level) : [...kept, level];
      const levels = { ...state.levels };
      if (all.every((item) => next.includes(item))) delete levels[axis];
      else levels[axis] = next;
      return { levels };
    }),
  removeTerm: (id) =>
    set((state) => {
      const [kind, key] = id.split(/:(.*)/s);
      if (kind === "distribution") return { distribution: [] };
      const drop = <T,>(record: Record<string, T>) => {
        const next = { ...record };
        delete next[key];
        return next;
      };
      if (kind === "range") return { ranges: drop(state.ranges) };
      if (kind === "picked") return { picked: drop(state.picked) };
      if (kind === "levels") return { levels: drop(state.levels) };
      return {};
    }),
  clearDistribution: () => set({ distribution: [] }),
  clearParallel: () => set({ ranges: {}, picked: {} }),
  clearAll: () => set({ distribution: [], ranges: {}, picked: {}, levels: {} }),
  pin: (hash) => {
    const { pinned } = get();
    if (pinned.includes(hash)) return true;
    if (pinned.length >= MAX_PINNED) return false;
    set({ pinned: [...pinned, hash] });
    return true;
  },
  unpin: (hash) => set((state) => ({ pinned: state.pinned.filter((item) => item !== hash) })),
  reset: () => set({ ...FRESH }),
}));

/** The scenarios every panel shows: the rows the intersection of every term lets through. */
export function useFilteredRows(except?: Except): SweepRow[] {
  const rows = useInterrogate((state) => state.rows);
  const terms = useTerms();
  return useMemo(() => filterRows(rows, terms, except), [rows, terms, except]);
}

/** The config hashes of the filtered scenarios, in row order: what the sensitivity panel posts
 * to /sweep/{id}/spread as ``config_hashes``. */
export function useFilteredHashes(): string[] {
  const filtered = useFilteredRows();
  return useMemo(() => hashesOf(filtered), [filtered]);
}

export function useTerms(): Terms {
  const metric = useInterrogate((state) => state.metric);
  const distribution = useInterrogate((state) => state.distribution);
  const ranges = useInterrogate((state) => state.ranges);
  const picked = useInterrogate((state) => state.picked);
  const levels = useInterrogate((state) => state.levels);
  const showInadmissible = useInterrogate((state) => state.showInadmissible);
  return useMemo(
    () => ({ metric, distribution, ranges, picked, levels, showInadmissible }),
    [metric, distribution, ranges, picked, levels, showInadmissible],
  );
}

export { AXIS_COLUMNS };
