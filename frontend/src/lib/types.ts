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

export interface UploadResponse {
  status: string;
  file_path: string;
  [key: string]: JsonValue;
}

export interface ApiStatusResponse {
  status: string;
  [key: string]: JsonValue;
}