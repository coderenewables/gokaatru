export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type SessionStep =
  | "timeseries"
  | "datamodel"
  | "config"
  | "cleaning"
  | "shear_timeseries"
  | "shear_table"
  | "roughness_timeseries"
  | "roughness_table"
  | "era5_nodes"
  | "era5_extract"
  | "era5_interpolate"
  | "ltc"
  | "ensemble";

export type SessionSummaryMetric = JsonValue | string[] | number | boolean | null;

export interface ApiHealthResponse {
  status: string;
  service: string;
}

export interface CreateSessionResponse {
  status: string;
  session_id: string;
  workspace_dir: string;
  created_at: string | null;
  completed_steps: SessionStep[];
}

export interface SessionSummaryResponse {
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
  completed_steps: SessionStep[];
}

export interface SensorRecord {
  name: string;
  height_m: number;
  sensor_type: string;
  data_coverage_pct: number;
  record_count: number;
}

export interface SensorsResponse {
  sensors: SensorRecord[];
}

export interface SensorCoverageResponse {
  sensor_name: string;
  total_records: number;
  valid_records: number;
  coverage_pct: number;
  gap_count: number;
  largest_gap_minutes: number;
  gaps_over_1_hour: number;
}

export interface RunConfigUpdate {
  key: string;
  value: JsonValue;
}

export interface UpdateRunConfigRequest {
  updates: RunConfigUpdate[];
}

export type RunConfigResponse = Record<string, JsonValue>;

export interface ConfigUpdateResponse {
  status: string;
  runconfig: RunConfigResponse;
  file_path: string;
}

export interface CleaningApplyResponse {
  status: string;
  rule: string;
  sensor: string;
  records_affected: number;
}

export interface CleaningLogEntry {
  rule_type: string;
  sensor: string;
  records_affected: number;
  applied_at: string;
  params: Record<string, JsonValue>;
  start_date: string;
  end_date: string;
}

export interface CleaningLogResponse {
  entries: CleaningLogEntry[];
}

export interface TableBuildResponse {
  method: string;
  aggregation: string;
  table: number[][];
}

export interface ExtrapolationResponse {
  status: string;
  column_name: string;
  method_counts: {
    direct: number;
    interpolated: number;
    extrapolated: number;
  };
}

export interface Era5Node {
  latitude: number;
  longitude: number;
  distance_km: number;
  bearing: string;
}

export interface Era5NodesResponse {
  nodes: Era5Node[];
  grid_resolution_deg: number;
}

export interface Era5ExtractResponse {
  status: string;
  latitude: number;
  longitude: number;
  rows: number;
  start: string;
  end: string;
  variables: string[];
  cached: boolean;
}

export interface Era5InterpolationResponse {
  status: string;
  rows: number;
  method: string;
  variables: string[];
}

export interface LtcRunResponse {
  status: string;
  algorithm: string;
  [key: string]: JsonValue;
}

export interface ClippingAnalysisPoint {
  start_year: number;
  n_years: number;
  mean_speed: number;
  iav: number;
  lta_ratio: number;
  historic_uncertainty: number;
  climate_uncertainty: number;
  combined_uncertainty: number;
}

export interface ClippingAnalysisResponse {
  optimal_start_year: number;
  min_uncertainty: number;
  iav: number;
  analysis_data: ClippingAnalysisPoint[];
}

export interface HomogeneityDataset {
  name: string;
  recommended_start_year: number;
  pettitt_p_value: number;
  trend_per_year: number;
}

export interface HomogeneityAnalysisResponse {
  datasets: HomogeneityDataset[];
}

export interface HomogeneityApplyResponse {
  status: string;
  rows_before: number;
  rows_after: number;
  cutoff_year: number;
}

export interface UncertaintyResponse {
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
  inputs: {
    measurement_height_m: number;
    hub_height_m: number;
    shear_method: string;
    mcp_r_squared: number;
    concurrent_months: number;
    iav_pct: number;
    algorithm: string;
    is_interpolation: boolean;
  };
}

export type AnalysisSummaryResponse = Record<string, SessionSummaryMetric> & {
  completed_steps: SessionStep[];
};

export interface LtcResultSummary {
  algorithm: string;
  metrics: Record<string, JsonValue>;
  result_file?: string;
  rows: number;
}

export interface LtcResultsResponse {
  results: LtcResultSummary[];
}

export interface EnsembleResultsResponse {
  available: boolean;
  rows?: number;
  columns?: string[];
}

export interface PlotResult {
  plotly_json: string;
  png_base64?: string | null;
  title: string;
}

export interface GeoJsonFeature {
  type: "Feature";
  geometry: {
    type: string;
    coordinates: number[];
  };
  properties: Record<string, JsonValue>;
}

export interface SiteMapResponse {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
}

export interface RunconfigExportResponse {
  status: string;
  file_path: string;
  runconfig: RunConfigResponse;
}

export interface UploadResponse {
  status: string;
  file_path: string;
  [key: string]: JsonValue;
}

export interface ApiStatusResponse {
  status: string;
  [key: string]: JsonValue;
}