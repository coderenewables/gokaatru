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

/** What each status means for whether a scenario counts. Only `fail` excludes. */
export const GATE_STATUS_MEANING: Record<GateStatus, string> = {
  pass: "Within the preferred standard.",
  warn: "Below the preferred standard but still counted in every statistic, and marked.",
  fail: "Excluded from all reported statistics. Still shown in the table.",
  not_applicable:
    "This gate had nothing to measure on this scenario — distinct from a pass, so an absent check is never mistaken for a satisfied one.",
  marked: "Not a defect, but kept visible. Never excludes.",
};

/**
 * Human-readable description of every gate, mirroring `server/core/admissibility.py`.
 *
 * Kept here rather than fetched so the Gates view can explain a gate that no scenario
 * happened to trip — a reader needs to know what *was* checked, not only what failed.
 */
export interface GateMeta {
  label: string;
  measures: string;
  appliesTo: string;
  /** Threshold keys on `GateThresholds`, for showing the values in force. */
  thresholdKeys: string[];
  /** Larger is worse (ratios, clip fractions) vs smaller is worse (coverage, months). */
  direction: "higher-is-worse" | "lower-is-worse" | "band" | "none";
}

export const GATE_META: Record<string, GateMeta> = {
  extrapolation_ratio: {
    label: "Extrapolation ratio",
    measures:
      "Hub height as a multiple of the reference height actually used, at the worst record. Beyond about 2×, the power-law assumption rather than the measurement determines the hub-height speed.",
    appliesTo: "Scenarios that extrapolate. Not applicable when hub height is bracketed by measurements.",
    thresholdKeys: ["extrapolation_ratio_warn", "extrapolation_ratio_fail"],
    direction: "higher-is-worse",
  },
  concurrent_period: {
    label: "Concurrent period",
    measures:
      "Months of measured/reference overlap the correction was fitted on. A short overlap cannot capture a full seasonal cycle.",
    appliesTo: "Every scenario with an LTC result.",
    thresholdKeys: ["concurrent_months_warn", "concurrent_months_fail"],
    direction: "lower-is-worse",
  },
  mean_shear_alpha: {
    label: "Mean shear α",
    measures:
      "Mean of the 12×24 power-law table. Below zero is not physical for resource assessment; the upper bound admits dense forest and urban terrain plus stability-skewed sites.",
    appliesTo: "Power-law scenarios. Not applicable to the log law.",
    thresholdKeys: ["mean_alpha_warn_low", "mean_alpha_warn_high", "mean_alpha_fail_low", "mean_alpha_fail_high"],
    direction: "band",
  },
  alpha_cell_dispersion: {
    label: "α cell dispersion",
    measures:
      "Share of month-hour cells outside the wider per-cell band. Gated on the fraction rather than any single cell, so one extreme winter-night cell does not fail a sound table.",
    appliesTo: "Power-law scenarios.",
    thresholdKeys: ["cell_alpha_low", "cell_alpha_high", "cell_outside_fraction_warn", "cell_outside_fraction_fail"],
    direction: "higher-is-worse",
  },
  shear_table_coverage: {
    label: "Shear-table coverage",
    measures:
      "Share of the 288 month-hour cells holding enough records to mean anything. Unobserved cells are back-filled with the series mean, and the table is applied to the full long-term reference — so a low share means real months are corrected with a synthetic value.",
    appliesTo: "Fitted-shear scenarios. Not applicable to an analyst-supplied exponent.",
    thresholdKeys: ["min_records_per_cell", "cell_coverage_warn", "cell_coverage_fail"],
    direction: "lower-is-worse",
  },
  roughness_clipping: {
    label: "Roughness clipping",
    measures:
      "Share of the z0 series sitting on a clip bound rather than a fit. exp(−intercept/slope) diverges as the profile flattens, so a high share means the log-law fit is not resolving the surface at all.",
    appliesTo: "Log-law scenarios only.",
    thresholdKeys: ["roughness_clip_warn", "roughness_clip_fail"],
    direction: "higher-is-worse",
  },
  sector_records: {
    label: "Sector records",
    measures: "Record count in the thinnest directional sector.",
    appliesTo: "Directional-shear scenarios, which the extrapolation path cannot yet consume — so currently always not applicable.",
    thresholdKeys: ["sector_records_warn", "sector_records_fail"],
    direction: "lower-is-worse",
  },
  shear_provenance: {
    label: "Shear provenance",
    measures:
      "Whether the exponent was fitted from measurements or supplied by the analyst. A supplied value satisfies the α band trivially, so the band cannot be what catches it.",
    appliesTo: "Every scenario. Emits “marked”, never a failure.",
    thresholdKeys: [],
    direction: "none",
  },
};

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
  /** Count of completed scenarios failing each gate, worst first. */
  gate_failures?: Record<string, number>;
  /**
   * Set only when *no* scenario was admissible. An empty distribution with nothing
   * explaining it reads as "no signal" rather than "your threshold excluded everything".
   */
  diagnosis?: string | null;
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
