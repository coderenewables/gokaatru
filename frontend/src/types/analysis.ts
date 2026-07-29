// Type model for the GoKaatru workflow frontend.
//
// Mirrors the backend response shapes documented in
// WORKFLOW_FRONTEND_SPEC.md §1.5 and the central config object in §8.
import { z } from "zod";

// ---------------------------------------------------------------------------
// Stage identity (spec §3.3)
// ---------------------------------------------------------------------------

export type StageId =
  | "data"
  | "cleaning"
  | "reanalysis"
  | "explore"
  | "shear"
  | "reanalysis_extrapolation"
  | "ltc"
  | "clipping"
  | "ensemble";

export type StageStatus = "locked" | "available" | "in_progress" | "done" | "error";

// ---------------------------------------------------------------------------
// Backend response interfaces (spec §1.5)
// ---------------------------------------------------------------------------

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface ApiHealthResponse {
  status: string;
  service: string;
}

export interface SessionSummary {
  session_id: string;
  workspace_dir: string | null;
  created_at: string | null;
  updated_at: string | null;
  project_name: string | null;
  measurement_type: string | null;
  hub_height_m: number | null;
  timeseries_loaded: boolean;
  datamodel_loaded: boolean;
  era5_nodes_loaded: boolean;
  era5_interpolated_loaded: boolean;
  ltc_algorithms: string[];
  completed_steps: string[];
}

export interface AnalysisSummary {
  project_name?: string | null;
  hub_height_m?: number | null;
  timeseries_loaded?: boolean;
  sensor_mapping_loaded?: boolean;
  sensor_count?: number;
  avg_coverage_pct?: number | null;
  cleaning_rules_applied?: number;
  shear_table_ready?: boolean;
  roughness_table_ready?: boolean;
  era5_nodes_loaded?: boolean;
  era5_data_sets_loaded?: number;
  era5_interpolated_ready?: boolean;
  ltc_algorithms_run?: string[];
  ensemble_ready?: boolean;
  scenario_count?: number;
  coordinate?: { latitude: number; longitude: number; elevation_m?: number } | null;
  completed_steps?: string[];
}

export type SensorType = "wind_speed" | "wind_direction" | "temperature" | "pressure" | (string & {});

export interface SensorRow {
  name: string;
  height_m: number;
  sensor_type: SensorType;
  data_coverage_pct: number;
  record_count: number;
}

export interface CoverageDetail {
  sensor: string;
  total_records: number;
  valid_records: number;
  coverage_pct: number;
  largest_gap_minutes: number;
  gaps_over_1_hour: number;
}

export interface SensorStatistics {
  sensor_name: string;
  mean: number;
  median: number;
  std: number;
  min_value: number;
  max_value: number;
  count: number;
  coverage_pct: number;
  weibull_k: number | null;
  weibull_A: number | null;
  monthly_means: number[];
  diurnal_means: number[];
  percentiles: Record<string, number>;
}

export interface WindClimateSummary {
  speed_sensor: string;
  record_count: number;
  mean_speed: number;
  cube_mean_speed: number;
  weibull_k: number;
  weibull_A: number;
  weibull_rmse: number;
  exceedance: { p50: number; p75: number; p90: number; p95: number };
  direction: {
    sensor_name: string;
    mean_direction_deg: number;
    circular_variance: number;
    prevailing_sector: string;
  } | null;
  sectors: Array<{
    center_deg: number;
    label: string;
    occurrence_pct: number;
    mean_speed: number;
    energy_pct: number;
  }>;
}

export interface VerticalStructureSummary {
  mean_profile: Array<{ height_m: number; mean_speed: number }>;
  power_law_alpha: number;
  power_law_r_squared: number;
  roughness_length_m: number;
  alpha: { record_count: number; mean: number; median: number; std: number; p10: number; p90: number };
  veer: { record_count: number; mean_deg_per_100m: number; std_deg_per_100m: number } | null;
}

export interface TurbulenceSummary {
  speed_sensor: string;
  sd_sensor: string;
  record_count: number;
  mean_ti: number;
  p90_ti: number;
  representative_ti: number;
  iec_ti_at_15ms: number;
}

export interface EraNode {
  latitude: number;
  longitude: number;
  distance_km?: number;
  bearing?: string;
}

export interface HomogeneityDataset {
  name: string;
  recommended_start_year: number;
  pettitt_p_value: number;
  trend_per_year: number;
}

export interface LtcMetrics {
  algorithm: string;
  r_squared?: number;
  rmse?: number;
  mae?: number;
  mbe?: number;
  slope?: number;
  intercept?: number;
  threshold?: number;
  dog_leg_slope?: number;
  variance_ratio?: number;
  correlation?: number;
  concurrent_points?: number;
  total_corrected_points?: number;
  feature_importance?: Record<string, number>;
  [k: string]: unknown;
}

export interface LtcResultSummary {
  algorithm: string;
  metrics: LtcMetrics;
  result_file: string | null;
  rows: number;
}

export interface EnsembleSummary {
  available: boolean;
  rows?: number;
  columns?: string[];
  reference_columns?: string[];
}

export interface ClippingRow {
  start_year: number;
  n_years: number;
  mean_speed: number;
  iav: number;
  lta_ratio: number;
  historic_uncertainty: number;
  climate_uncertainty: number;
  combined_uncertainty: number;
}

export interface ClippingReport {
  optimal_start_year: number;
  min_uncertainty: number;
  iav: number;
  analysis_data: ClippingRow[];
}

export interface UncertaintyResult {
  total_uncertainty_pct: number;
  components: {
    measurement: number;
    vertical_extrapolation: number;
    mcp: number;
    future_variability: number;
  };
  p_factors: {
    p50: number;
    p75: number;
    p90: number;
    p99: number;
  };
  inputs: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Plot protocol (spec §1.4)
// ---------------------------------------------------------------------------

export interface PlotResult {
  plotly_json: string;
  png_base64: string | null;
  title: string;
}

export type PlotName =
  | "windrose"
  | "weibull"
  | "speed_distribution"
  | "exceedance_curve"
  | "direction_distribution"
  | "sector_speed"
  | "energy_rose"
  | "shear_alpha"
  | "wind_veer"
  | "diurnal"
  | "scatter"
  | "timeseries"
  | "timeseries_preview"
  | "cleaning_overlay"
  | "coverage_timeline"
  | "data_coverage"
  | "scenario_comparison"
  | "era5_comparison"
  | "era5_measured_overlay"
  | "shear_table"
  | "shear_profile"
  | "monthly_means"
  | "turbulence_intensity"
  | "ltc_comparison"
  | "ltc_scatter"
  | "ltc_residuals"
  | "ltc_monthly"
  | "ltc_convergence"
  | "annual_means"
  | "uncertainty_breakdown"
  | "uncertainty_tornado";

export interface PlotRequest {
  speed_sensor?: string;
  sensor_name?: string;
  sensor_names?: string;
  direction_sensor?: string;
  sensor_a?: string;
  sensor_b?: string;
  algorithm?: string;
  table_type?: string;
  total_pct?: number;
  measurement_pct?: number;
  vertical_pct?: number;
  mcp_pct?: number;
  future_pct?: number;
}

export const PLOT_NAMES: readonly PlotName[] = [
  "windrose",
  "weibull",
  "speed_distribution",
  "exceedance_curve",
  "direction_distribution",
  "sector_speed",
  "energy_rose",
  "shear_alpha",
  "wind_veer",
  "diurnal",
  "scatter",
  "timeseries",
  "timeseries_preview",
  "cleaning_overlay",
  "coverage_timeline",
  "data_coverage",
  "scenario_comparison",
  "era5_comparison",
  "era5_measured_overlay",
  "shear_table",
  "shear_profile",
  "monthly_means",
  "turbulence_intensity",
  "ltc_comparison",
  "ltc_scatter",
  "ltc_residuals",
  "ltc_monthly",
  "ltc_convergence",
  "annual_means",
  "uncertainty_breakdown",
  "uncertainty_tornado",
] as const;

// ---------------------------------------------------------------------------
// LTC algorithm path values (spec §1.5)
// ---------------------------------------------------------------------------

export const LTC_ALGORITHMS = [
  "linear_least_squares",
  "total_least_squares",
  "speedsort",
  "variance_ratio",
  "xgboost",
] as const;
export type LtcAlgorithm = (typeof LTC_ALGORITHMS)[number];

// ---------------------------------------------------------------------------
// Scenarios / workflow support types
// ---------------------------------------------------------------------------

export interface ScenarioSnapshot {
  name: string;
  created_at: string;
  config: Record<string, unknown>;
  results: Record<string, unknown>;
}

export interface WorkflowDispatchCapability {
  template_id: string;
  required_params: string[];
  optional_params: string[];
}

export interface WorkflowExecutionEvent {
  run_id: string;
  event_type: string;
  node_id?: string | null;
  status?: string | null;
  message?: string | null;
  timestamp: string;
}

export interface WorkflowExecutionResponse {
  run_id: string;
  status: string;
  node_statuses: Record<string, string>;
  events: WorkflowExecutionEvent[];
}

export interface WorkflowExecutionStatusResponse {
  run_id: string | null;
  is_running: boolean;
  cancelled: boolean;
  node_statuses: Record<string, string>;
  events: WorkflowExecutionEvent[];
}

export interface SharedDatasetSummary {
  dataset_id?: string;
  id?: string;
  name?: string;
  timeseries_filename?: string;
  datamodel_filename?: string;
  uploaded_at?: string;
  date_range?: { start: string; end: string };
  coverage_pct?: number;
  sensor_count?: number;
  [key: string]: unknown;
}

export interface DatasetPreview {
  dataset_id?: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  preview_rows?: Array<Record<string, unknown>>;
  total_rows?: number;
  start?: string;
  end?: string;
  timestep_minutes?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Central typed config object (spec §8) — the editing surface
// ---------------------------------------------------------------------------

export const measurementTypeSchema = z.enum([
  "mast",
  "lidar",
  "sodar",
  "floating-lidar",
  "hybrid",
]);
export type MeasurementType = z.infer<typeof measurementTypeSchema>;

export const sensorKindSchema = z.enum([
  "speed",
  "direction",
  "temperature",
  "pressure",
  "humidity",
  "quality",
  "other",
]);

export const shearMethodSchema = z.enum(["power_law", "log_law", "roughness", "windkit"]);

export const reanalysisProviderSchema = z.enum(["era5", "merra2", "brighthub", "windkit"]);

export const ltcAlgorithmConfigSchema = z.enum([
  "speedsort",
  "linear_least_squares",
  "total_least_squares",
  "variance_ratio",
  "xgboost",
  "ensemble",
  "windkit_linreg_mcp",
  "windkit_varrat_mcp",
]);

const locationSchema = z.object({
  latitude: z.number(),
  longitude: z.number(),
  elevationM: z.number(),
  region: z.string(),
  timeZone: z.string(),
});

const projectSchema = z.object({
  name: z.string().min(1),
  client: z.string(),
  measurementType: measurementTypeSchema,
  notes: z.string(),
});

const sensorSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  column: z.string(),
  kind: sensorKindSchema,
  heightM: z.number().nonnegative(),
  unit: z.string(),
});

const mastSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  latitude: z.number(),
  longitude: z.number(),
  elevationM: z.number(),
  boomOrientationDeg: z.number(),
  sensors: z.array(sensorSchema),
});

const datasetBindingSchema = z.object({
  sharedDatasetId: z.string(),
  timeseriesFileName: z.string(),
  datamodelFileName: z.string(),
  activeSensorNames: z.array(z.string()),
});

const cleaningRuleSchema = z.object({
  id: z.string().min(1),
  ruleType: z.string(),
  sensor: z.string(),
  params: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])),
  startDate: z.string(),
  endDate: z.string(),
});

const shearConfigSchema = z.object({
  method: shearMethodSchema,
  speedSensorPair: z.array(z.string()),
  directionSensor: z.string(),
  aggregation: z.enum(["mean", "median", "p90", "momm"]),
  targetHubHeightM: z.number().positive(),
  useWindKit: z.boolean(),
});

const reanalysisNodeSchema = z.object({
  provider: reanalysisProviderSchema,
  latitude: z.number(),
  longitude: z.number(),
  label: z.string(),
});

const reanalysisConfigSchema = z.object({
  preferredProvider: reanalysisProviderSchema,
  searchLatitude: z.number(),
  searchLongitude: z.number(),
  startDate: z.string(),
  endDate: z.string(),
  nodes: z.array(reanalysisNodeSchema),
});

const ltcConfigSchema = z.object({
  algorithms: z.array(ltcAlgorithmConfigSchema),
  shortColumn: z.string(),
  longColumn: z.string(),
  shortDirectionColumn: z.string(),
  longDirectionColumn: z.string(),
  measuredColumn: z.string(),
  uncertainty: z.object({
    measurementUncertaintyPct: z.number().nonnegative(),
    measurementHeightM: z.number().positive(),
    hubHeightM: z.number().positive(),
    shearMethod: z.string(),
    mcpRSquared: z.number().min(0).max(1),
    concurrentHours: z.number().positive(),
    algorithm: z.string(),
    iavPct: z.number().nonnegative(),
    shearStd: z.number().nonnegative(),
    isInterpolation: z.boolean(),
  }),
});

const workflowConfigSchema = z.object({
  mode: z.enum(["auto", "manual"]),
  snapshotName: z.string(),
});

const compareConfigSchema = z.object({
  branchSessionIds: z.array(z.string()),
  baselineLabel: z.string(),
});

export const windAnalysisConfigSchema = z.object({
  version: z.literal("2026-05"),
  project: projectSchema,
  site: locationSchema.extend({
    hubHeightM: z.number().positive(),
    rotorDiameterM: z.number().positive(),
  }),
  mast: z.object({
    primaryMastId: z.string().min(1),
    masts: z.array(mastSchema),
  }),
  inputs: datasetBindingSchema,
  cleaning: z.object({
    rules: z.array(cleaningRuleSchema),
    lastAppliedRuleId: z.string(),
  }),
  shear: shearConfigSchema,
  reanalysis: reanalysisConfigSchema,
  ltc: ltcConfigSchema,
  workflow: workflowConfigSchema,
  compare: compareConfigSchema,
});

export type WindAnalysisConfig = z.infer<typeof windAnalysisConfigSchema>;

// ---------------------------------------------------------------------------
// Activity log (store internal)
// ---------------------------------------------------------------------------

export interface ActivityEntry {
  id: string;
  label: string;
  timestamp: string;
  status: "ok" | "error";
  detail: string;
}
