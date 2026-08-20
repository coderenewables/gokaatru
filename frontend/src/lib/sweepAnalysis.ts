// Client-side analysis over the sweep result table (design doc §9.7).
//
// Kept on the client deliberately: the table is a few thousand rows, and filtering,
// grouping and percentile maths have to feel instant while an analyst brushes an axis.
// A round trip per interaction would make the Spread Explorer unusable.
//
// **Statistics are computed over admissible rows only** (design doc §7.7). Inadmissible
// scenarios stay in the table and render as a ghost layer, but they never enter a
// percentile — that distinction is the whole reason the gates exist.
import {
  AXIS_COLUMNS,
  METRIC_META,
  type AxisColumn,
  type MetricColumn,
  type ScenarioRow,
} from "../types/sweep";

export interface SpreadStats {
  count: number;
  min: number;
  p10: number;
  p50: number;
  p90: number;
  max: number;
  mean: number;
  /** Sample standard deviation; 0 when fewer than two values. */
  std: number;
  /** Full range as a percentage of the mean — the headline "spread" figure. */
  rangePctOfMean: number;
}

/** Rows that completed and passed every gate. The only rows statistics are taken over. */
export function admissibleRows(rows: ScenarioRow[]): ScenarioRow[] {
  return rows.filter((row) => row.status === "ok" && row.admissible);
}

/** Rows that completed but failed a gate — shown, never counted. */
export function inadmissibleRows(rows: ScenarioRow[]): ScenarioRow[] {
  return rows.filter((row) => row.status === "ok" && !row.admissible);
}

export function failedRows(rows: ScenarioRow[]): ScenarioRow[] {
  return rows.filter((row) => row.status === "failed");
}

export function metricValues(rows: ScenarioRow[], metric: MetricColumn): number[] {
  const values: number[] = [];
  for (const row of rows) {
    const value = row[metric];
    if (typeof value === "number" && Number.isFinite(value)) values.push(value);
  }
  return values;
}

/** Linear-interpolated percentile over a pre-sorted array. */
export function percentile(sorted: number[], fraction: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0];
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

export function spreadStats(rows: ScenarioRow[], metric: MetricColumn): SpreadStats | null {
  const values = metricValues(rows, metric);
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  const variance =
    values.length < 2
      ? 0
      : values.reduce((total, value) => total + (value - mean) ** 2, 0) / (values.length - 1);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  return {
    count: values.length,
    min,
    p10: percentile(sorted, 0.1),
    p50: percentile(sorted, 0.5),
    p90: percentile(sorted, 0.9),
    max,
    mean,
    std: Math.sqrt(variance),
    rangePctOfMean: mean === 0 ? 0 : ((max - min) / Math.abs(mean)) * 100,
  };
}

export interface AxisContribution {
  axis: AxisColumn;
  /** Distinct levels present in the rows analysed. */
  levels: number;
  /** Share of total variance explained by this axis, 0-1. */
  share: number;
  /** Spread between the best and worst level means, in metric units. */
  swing: number;
  /** Level means, for the tornado and the interaction heatmap. */
  levelMeans: Array<{ level: string; mean: number; count: number }>;
}

/**
 * Decompose the variance of one metric across the axes (design doc §7.9).
 *
 * One-way between-group variance per axis, normalised so the shares sum to 1. This is a
 * first-order decomposition: it attributes nothing to interactions, so the shares
 * describe main effects and will not account for the whole spread when axes interact.
 * Stated rather than hidden, because §8.1 uses these shares to size the uncertainty
 * substitution and a reader needs to know what they do and do not cover.
 */
export function decomposeVariance(
  rows: ScenarioRow[],
  metric: MetricColumn,
): AxisContribution[] {
  const usable = rows.filter((row) => {
    const value = row[metric];
    return typeof value === "number" && Number.isFinite(value);
  });
  if (usable.length < 2) return [];

  const all = metricValues(usable, metric);
  const grandMean = all.reduce((total, value) => total + value, 0) / all.length;

  const raw = AXIS_COLUMNS.map<AxisContribution & { between: number }>((axis) => {
    const groups = new Map<string, number[]>();
    for (const row of usable) {
      const level = String(row[axis] ?? "—");
      const value = row[metric] as number;
      const bucket = groups.get(level);
      if (bucket) bucket.push(value);
      else groups.set(level, [value]);
    }
    const levelMeans = [...groups.entries()]
      .map(([level, values]) => ({
        level,
        mean: values.reduce((total, value) => total + value, 0) / values.length,
        count: values.length,
      }))
      .sort((a, b) => b.mean - a.mean);

    // Between-group sum of squares: how much of the spread this axis alone explains.
    const between = levelMeans.reduce(
      (total, entry) => total + entry.count * (entry.mean - grandMean) ** 2,
      0,
    );
    const swing =
      levelMeans.length < 2 ? 0 : levelMeans[0].mean - levelMeans[levelMeans.length - 1].mean;
    return { axis, levels: groups.size, share: 0, swing, levelMeans, between };
  });

  const total = raw.reduce((sum, entry) => sum + entry.between, 0);
  return raw
    .map(({ between, ...entry }) => ({
      ...entry,
      share: total === 0 ? 0 : between / total,
    }))
    .sort((a, b) => b.share - a.share);
}

/** Distinct levels present for an axis, in stable order. */
export function axisLevels(rows: ScenarioRow[], axis: AxisColumn): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    const value = row[axis];
    if (value != null) seen.add(String(value));
  }
  return [...seen].sort();
}

export type AxisFilters = Partial<Record<AxisColumn, string[]>>;

/** Apply axis-level filters. An axis with no selection does not filter. */
export function filterRows(rows: ScenarioRow[], filters: AxisFilters): ScenarioRow[] {
  const active = Object.entries(filters).filter(([, levels]) => levels && levels.length > 0);
  if (active.length === 0) return rows;
  return rows.filter((row) =>
    active.every(([axis, levels]) => (levels as string[]).includes(String(row[axis as AxisColumn]))),
  );
}

export function formatMetric(value: unknown, metric: MetricColumn): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const meta = METRIC_META[metric];
  const shown = value.toLocaleString(undefined, {
    minimumFractionDigits: meta.precision,
    maximumFractionDigits: meta.precision,
  });
  return meta.unit ? `${shown} ${meta.unit}` : shown;
}

/** Simple equal-width histogram, for the distribution panel. */
export function histogram(values: number[], bins = 24): Array<{ x0: number; x1: number; count: number }> {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ x0: min, x1: max, count: values.length }];
  const width = (max - min) / bins;
  const buckets = Array.from({ length: bins }, (_, index) => ({
    x0: min + index * width,
    x1: min + (index + 1) * width,
    count: 0,
  }));
  for (const value of values) {
    const index = Math.min(bins - 1, Math.floor((value - min) / width));
    buckets[index].count += 1;
  }
  return buckets;
}

/** Render the result table as CSV, for the export in §9.5. */
export function toCsv(rows: ScenarioRow[]): string {
  if (rows.length === 0) return "";
  const columns = Object.keys(rows[0]);
  const escape = (value: unknown): string => {
    if (value == null) return "";
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ].join("\n");
}
