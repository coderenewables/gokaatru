import type { ScenarioSnapshot } from "./api";

export interface ScenarioComparisonEntry {
  label: string;
  scenario: ScenarioSnapshot;
}

export interface ScenarioMetricRow {
  key: string;
  label: string;
  unit: string;
  values: Record<string, string | number | null>;
}

export interface ScenarioDiffEntry {
  key: string;
  baseline: unknown;
  compare: unknown;
}

export interface ScenarioComparisonResult {
  labels: string[];
  scenarioNames: string[];
  metrics: ScenarioMetricRow[];
  diffs: Record<string, ScenarioDiffEntry[]>;
}

const metricOrder = [
  "long_term_mean_speed",
  "ensemble_mean_speed",
  "total_uncertainty_pct",
  "p50",
  "p75",
  "p90",
  "p99",
  "measurement_uncertainty_pct",
  "vertical_uncertainty_pct",
  "mcp_uncertainty_pct",
  "future_uncertainty_pct",
] as const;

const metricUnits: Record<string, string> = {
  long_term_mean_speed: "m/s",
  ensemble_mean_speed: "m/s",
  total_uncertainty_pct: "%",
  measurement_uncertainty_pct: "%",
  vertical_uncertainty_pct: "%",
  mcp_uncertainty_pct: "%",
  future_uncertainty_pct: "%",
};

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (value) => value.toUpperCase())
    .replace(/Pct\b/g, "%")
    .replace(/Mcp/g, "MCP")
    .replace(/P(\d+)/g, "P$1");
}

function flattenRecord(value: unknown, prefix = ""): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return prefix ? { [prefix]: value } : {};
  }

  const flattened: Record<string, unknown> = {};
  for (const [key, childValue] of Object.entries(value)) {
    const nextPrefix = prefix ? `${prefix}.${key}` : key;
    if (typeof childValue === "object" && childValue !== null && !Array.isArray(childValue)) {
      Object.assign(flattened, flattenRecord(childValue, nextPrefix));
      continue;
    }
    flattened[nextPrefix] = childValue;
  }
  return flattened;
}

function buildMetricKeys(entries: ScenarioComparisonEntry[]): string[] {
  const union = new Set<string>();
  for (const entry of entries) {
    for (const key of Object.keys(entry.scenario.results ?? {})) {
      union.add(key);
    }
  }

  const ordered = metricOrder.filter((key) => union.has(key));
  const remainder = [...union].filter((key) => !metricOrder.includes(key as (typeof metricOrder)[number])).sort();
  return [...ordered, ...remainder];
}

function toDisplayValue(value: unknown): string | number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "number" || typeof value === "string") {
    return value;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return JSON.stringify(value);
}

export function buildScenarioComparison(entries: ScenarioComparisonEntry[]): ScenarioComparisonResult | null {
  if (entries.length < 2) {
    return null;
  }

  const metricKeys = buildMetricKeys(entries);
  const metrics = metricKeys.map((key) => ({
    key,
    label: humanizeKey(key),
    unit: metricUnits[key] ?? "",
    values: Object.fromEntries(entries.map((entry) => [entry.label, toDisplayValue(entry.scenario.results?.[key])])),
  }));

  const [baseline, ...others] = entries;
  const baselineConfig = flattenRecord(baseline.scenario.config);
  const diffs = Object.fromEntries(
    others.map((entry) => {
      const compareConfig = flattenRecord(entry.scenario.config);
      const keys = new Set([...Object.keys(baselineConfig), ...Object.keys(compareConfig)]);
      const items = [...keys]
        .sort()
        .filter((key) => baselineConfig[key] !== compareConfig[key])
        .map((key) => ({
          key,
          baseline: baselineConfig[key],
          compare: compareConfig[key],
        }));
      return [`${baseline.label}<->${entry.label}`, items];
    }),
  );

  return {
    labels: entries.map((entry) => entry.label),
    scenarioNames: entries.map((entry) => entry.scenario.name),
    metrics,
    diffs,
  };
}
