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
  type GateStatus,
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

export interface ValueBucket {
  value: number;
  count: number;
}

/**
 * Group values by the number each one actually displays as, for the distribution panel.
 *
 * Sweep axes are discrete/gridded (a handful of shear models, sensor policies, reference
 * sources...), so scenarios routinely land on the exact same or near-identical metric value
 * rather than spreading continuously. An equal-width histogram over `[min, max]` split that
 * clustering into a fixed number of arbitrary ranges regardless of how the data actually
 * fell, producing a chart with a few tall occupied bins and wide empty gaps between them.
 * Grouping by the rounded (displayed) value instead means every bar corresponds to a real
 * cluster of scenarios, and there are no empty bars to begin with.
 */
export function valueHistogram(values: number[], precision: number): ValueBucket[] {
  const counts = new Map<number, number>();
  for (const value of values) {
    const rounded = Number(value.toFixed(precision));
    counts.set(rounded, (counts.get(rounded) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value - b.value);
}

export interface GateSummary {
  gate: string;
  counts: Record<GateStatus, number>;
  /** Scenarios this gate excluded outright. */
  failedRows: ScenarioRow[];
  /** Scenarios it flagged without excluding. */
  warnedRows: ScenarioRow[];
  markedRows: ScenarioRow[];
  /** Range of the measured value across scenarios where the gate had something to measure. */
  valueRange: { min: number; max: number } | null;
  /** True when this gate excluded every completed scenario. */
  excludedEverything: boolean;
}

/**
 * Summarise every gate across a result set (design doc §7.7).
 *
 * Derived from the `gate_*` columns rather than a separate payload, so a gate added on
 * the backend appears here without frontend work — the same reasoning as `Disclosure`.
 */
export function summariseGates(rows: ScenarioRow[]): GateSummary[] {
  const completed = rows.filter((row) => row.status === "ok");
  const names = new Set<string>();
  for (const row of completed) {
    for (const key of Object.keys(row)) {
      if (key.startsWith("gate_") && !key.endsWith("_value")) names.add(key.slice(5));
    }
  }

  return [...names]
    .map<GateSummary>((gate) => {
      const counts: Record<GateStatus, number> = {
        pass: 0,
        warn: 0,
        fail: 0,
        not_applicable: 0,
        marked: 0,
      };
      const failedRows: ScenarioRow[] = [];
      const warnedRows: ScenarioRow[] = [];
      const markedRows: ScenarioRow[] = [];
      const values: number[] = [];

      for (const row of completed) {
        const status = row[`gate_${gate}`] as GateStatus | undefined;
        if (!status) continue;
        counts[status] = (counts[status] ?? 0) + 1;
        if (status === "fail") failedRows.push(row);
        if (status === "warn") warnedRows.push(row);
        if (status === "marked") markedRows.push(row);
        const value = row[`gate_${gate}_value`];
        if (typeof value === "number" && Number.isFinite(value)) values.push(value);
      }

      return {
        gate,
        counts,
        failedRows,
        warnedRows,
        markedRows,
        valueRange: values.length
          ? { min: Math.min(...values), max: Math.max(...values) }
          : null,
        excludedEverything: completed.length > 0 && counts.fail === completed.length,
      };
    })
    // Gates that excluded something first, then those that merely warned, then the rest.
    .sort(
      (a, b) =>
        b.counts.fail - a.counts.fail ||
        b.counts.warn - a.counts.warn ||
        a.gate.localeCompare(b.gate),
    );
}

/** The gate value on one row, when it had something to measure. */
export function gateValue(row: ScenarioRow, gate: string): number | null {
  const value = row[`gate_${gate}_value`];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
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
