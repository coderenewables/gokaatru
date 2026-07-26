// Scenario-compare helpers (spec §7 / Phase G).
//
// The backend POST /workflow/compare returns metrics, config diffs, and Plotly
// figures. This module shapes them for the Compare view.
import type { WorkflowCompareMetric, WorkflowCompareDiffEntry } from "../lib/api";

export interface MetricRow {
  name: string;
  unit: string;
  values: Record<string, number | null>;
  /** Per-session delta vs the first (baseline) session, when computable. */
  deltas: Record<string, number | null>;
}

export function toMetricRows(metrics: WorkflowCompareMetric[]): MetricRow[] {
  return metrics.map((m) => {
    const deltas: Record<string, number | null> = {};
    const sessionIds = Object.keys(m.values);
    const baselineId = sessionIds[0];
    const baseline = baselineId != null ? m.values[baselineId] : undefined;
    for (const id of sessionIds) {
      const v = m.values[id];
      deltas[id] = baseline != null && v != null ? v - baseline : null;
    }
    return { name: m.name, unit: m.unit, values: m.values, deltas };
  });
}

export function flattenConfigDiff(
  diff: Record<string, WorkflowCompareDiffEntry[]>,
): Array<{ pair: string; entries: WorkflowCompareDiffEntry[] }> {
  return Object.entries(diff).map(([pair, entries]) => ({ pair, entries }));
}

export function formatMetricValue(value: number | null | undefined, unit: string): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (unit === "%") return `${value.toFixed(2)}%`;
  if (unit === "m/s") return `${value.toFixed(2)} m/s`;
  return value.toFixed(3);
}
