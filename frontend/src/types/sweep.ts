// Scenario-sweep types, mirroring the backend result schema (design doc §7.8).
//
// The engine emits one flat row per scenario: axis values, metrics, and one column per
// admissibility gate. Every view in the Analysis Engine tab is a projection of that
// table, so this file is the contract between the two halves and should change only
// when `server/core/scenario_result.py` does.

/** Axis columns — a scenario's position in the space (design doc §3). */
export const AXIS_COLUMNS = [
  "shear_fit_policy",
  "reference_policy",
  "shear_model",
  "reference_source",
  "ltc_algorithm",
] as const;

export type AxisColumn = (typeof AXIS_COLUMNS)[number];

/** Human labels for the axes, used everywhere an axis is named in the UI. */
export const AXIS_LABELS: Record<AxisColumn, string> = {
  shear_fit_policy: "Shear-fit sensors (A1)",
  reference_policy: "Extrapolation reference (A2)",
  shear_model: "Vertical profile (B)",
  reference_source: "Long-term reference (C)",
  ltc_algorithm: "LTC method (D)",
};

/** The two pinned headline metrics, then the secondary ones (design doc §11). */
export const METRIC_COLUMNS = [
  "long_term_mean_speed_mps",
  "indicative_gross_aep_mwh",
  "capacity_factor",
  "energy_sensitivity_factor",
  "total_uncertainty_pct",
  "u_measurement_pct",
  "u_vertical_pct",
  "u_mcp_pct",
  "u_future_pct",
  "ltc_r_squared",
  "concurrent_months",
  "mean_shear_alpha",
  "extrapolation_ratio_max",
] as const;

export type MetricColumn = (typeof METRIC_COLUMNS)[number];

export interface MetricMeta {
  label: string;
  unit: string;
  /** Decimals to show. */
  precision: number;
  /** Pinned metrics are always offered first and never hidden. */
  headline?: boolean;
}

export const METRIC_META: Record<MetricColumn, MetricMeta> = {
  long_term_mean_speed_mps: { label: "Long-term mean speed", unit: "m/s", precision: 3, headline: true },
  indicative_gross_aep_mwh: { label: "Indicative gross AEP", unit: "MWh/yr", precision: 0, headline: true },
  capacity_factor: { label: "Capacity factor", unit: "", precision: 4 },
  energy_sensitivity_factor: { label: "Energy sensitivity S", unit: "", precision: 3 },
  total_uncertainty_pct: { label: "Total uncertainty", unit: "%", precision: 2 },
  u_measurement_pct: { label: "Measurement uncertainty", unit: "%", precision: 2 },
  u_vertical_pct: { label: "Vertical uncertainty", unit: "%", precision: 2 },
  u_mcp_pct: { label: "MCP uncertainty", unit: "%", precision: 2 },
  u_future_pct: { label: "Future variability", unit: "%", precision: 2 },
  ltc_r_squared: { label: "LTC R²", unit: "", precision: 3 },
  concurrent_months: { label: "Concurrent period", unit: "months", precision: 1 },
  mean_shear_alpha: { label: "Mean shear α", unit: "", precision: 4 },
  extrapolation_ratio_max: { label: "Max extrapolation ratio", unit: "×", precision: 2 },
};

export const HEADLINE_METRICS: MetricColumn[] = METRIC_COLUMNS.filter(
  (name) => METRIC_META[name].headline,
);

/** Gate verdicts. `not_applicable` is not a pass; `marked` is not a failure. */
export type GateStatus = "pass" | "warn" | "fail" | "not_applicable" | "marked";

/** One row of the sweep result table. Flat by design — see the backend module docstring. */
export interface ScenarioRow {
  config_hash: string;
  fixed_prefix_hash: string;
  status: "ok" | "failed";
  admissible: boolean;
  failed_gates: string;
  warned_gates: string;
  marked_gates: string;
  error: string | null;
  shear_fit_policy: string | null;
  reference_policy: string | null;
  shear_model: string | null;
  reference_source: string | null;
  ltc_algorithm: string | null;
  /** Metric columns are nullable — a failed scenario has none. */
  [key: string]: string | number | boolean | null | undefined;
}

export interface SweepCounts {
  planned: number;
  run: number;
  completed: number;
  failed: number;
  admissible: number;
  inadmissible: number;
}

export interface SweepManifestScenario {
  config_hash: string;
  status: string;
  admissible: boolean;
  runconfig: string;
  shear_fit_policy?: string | null;
  reference_policy?: string | null;
  shear_model?: string | null;
  reference_source?: string | null;
  ltc_algorithm?: string | null;
}

export interface SweepManifest {
  sweep_id: string;
  started_at: string;
  finished_at: string;
  stopped_early: boolean;
  fixed_prefix_hash: string;
  spec: Record<string, unknown>;
  thresholds: Record<string, number>;
  counts: SweepCounts;
  scenarios: SweepManifestScenario[];
}

export interface SweepOutcome {
  manifest: SweepManifest;
  results: ScenarioRow[];
}

export interface SweepSummary {
  sweep_id: string;
  started_at: string | null;
  finished_at: string | null;
  counts: SweepCounts;
  fixed_prefix_hash: string;
}

/** One axis level, with whether this session can actually run it and why not. */
export interface AxisLevel {
  name: string;
  available: boolean;
  reason?: string | null;
  resolved_columns?: string[];
  resolved_heights_m?: number[];
  can_fit_shear?: boolean;
  detail?: Record<string, unknown>;
}

export interface SweepAxes {
  sensor_policies: AxisLevel[];
  shear_models: AxisLevel[];
  reference_sources: AxisLevel[];
  power_curves: string[];
  known_sensor_policies: string[];
  default_thresholds: Record<string, number>;
}

export interface SweepRequestBody {
  shear_fit_policies: string[];
  reference_policies: string[];
  shear_models: string[];
  reference_sources: string[];
  ltc_algorithms: string[];
  hub_height_m?: number | null;
  analyst_shear_alpha?: number | null;
  thresholds?: Record<string, number> | null;
  sweep_id?: string | null;
}

export interface SweepEstimate {
  leaf_count: number;
  prefix_count: number;
  spec: Record<string, unknown>;
}

/** A progress event from the SSE stream (design doc §9.2). */
export interface SweepProgressEvent {
  event:
    | "sweep_started"
    | "prefix_started"
    | "prefix_completed"
    | "scenario_completed"
    | "scenario_failed"
    | "sweep_stopped"
    | "sweep_finished"
    | "sweep_error"
    | "sweep_result";
  completed?: number;
  total?: number;
  config_hash?: string | null;
  detail?: Record<string, unknown>;
  error?: string;
  manifest?: SweepManifest;
}

/** The LTC methods the engine can run. Mirrors `LTC_ALGORITHMS` on the backend. */
export const LTC_ALGORITHMS = [
  "variance_ratio",
  "linear_least_squares",
  "total_least_squares",
  "speedsort",
  "xgboost",
] as const;
