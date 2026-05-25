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

export interface SharedDatasetSummary {
  dataset_id?: string;
  id?: string;
  name?: string;
  timeseries_filename?: string;
  datamodel_filename?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface DatasetPreview {
  dataset_id?: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  preview_rows?: Array<Record<string, unknown>>;
  [key: string]: unknown;
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

export interface WorkflowSnapshotSummary {
  name: string;
  saved_at: string;
}

export interface WorkflowForkBranchResponse {
  status: string;
  parent_session_id: string;
  branch_session_id: string;
  branch_name: string;
  from_node_id?: string | null;
}

export interface WorkflowCompareMetric {
  name: string;
  unit: string;
  values: Record<string, number | null>;
}

export interface WorkflowCompareDiffEntry {
  key: string;
  a: unknown;
  b: unknown;
}

export interface WorkflowComparePlot {
  title: string;
  plotly_json: string;
}

export interface WorkflowCompareResponse {
  status: string;
  session_ids: string[];
  metrics: WorkflowCompareMetric[];
  config_diff: Record<string, WorkflowCompareDiffEntry[]>;
  plots: {
    weibull?: WorkflowComparePlot | null;
    windrose: WorkflowComparePlot[];
    ltc_scatter?: WorkflowComparePlot | null;
    uncertainty_tornado?: WorkflowComparePlot | null;
  };
}

export interface ScenarioSnapshot {
  name: string;
  created_at: string;
  config: Record<string, unknown>;
  results: Record<string, unknown>;
}

export interface BrightHubStatusResponse {
  authenticated: boolean;
  has_token: boolean;
}

export interface BrightHubLocation {
  uuid: string;
  name: string;
  latitude_ddeg?: number | null;
  longitude_ddeg?: number | null;
  measurement_station_type_id?: string | number | null;
  [key: string]: unknown;
}

export interface BrightHubImportLocationPayload {
  uuid: string;
  name?: string;
  latitude_ddeg?: number | null;
  longitude_ddeg?: number | null;
  apply_cleaning_log?: boolean;
  apply_cleaning_rules?: boolean;
  apply_calibration?: boolean;
  apply_deadband_offset?: boolean;
  apply_orientation_offset?: boolean;
}

export interface BrightHubImportLocationResponse {
  status: string;
  uuid: string;
  timeseries_rows: number;
  timeseries_columns: string[];
  timeseries_start?: string | null;
  timeseries_end?: string | null;
  datamodel_heights: number[];
  project_name?: string | null;
  measurement_type?: string | null;
  location?: Record<string, unknown> | null;
}

export interface BrightHubReanalysisNode {
  latitude_ddeg: number;
  longitude_ddeg: number;
  distance_sq?: number | null;
  [key: string]: unknown;
}

export interface BrightHubReanalysisNodesResponse {
  era5_nodes: BrightHubReanalysisNode[];
  merra2_nodes: BrightHubReanalysisNode[];
}

export interface BrightHubReanalysisDownloadItem {
  latitude: number;
  longitude: number;
  rows?: number | null;
  [key: string]: unknown;
}

export interface BrightHubReanalysisDownloadResponse {
  dataset: string;
  source: string;
  items: BrightHubReanalysisDownloadItem[];
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ToolCallResult {
  tool_name: string;
  arguments: Record<string, unknown>;
  result: unknown;
}

export interface ChatResponse {
  reply: string;
  tool_calls_executed: ToolCallResult[];
}

export interface WindKitResponse {
  status: string;
  result: unknown;
}

const SESSION_HEADER_NAME = "X-GoKaatru-Session";

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getDefaultApiBaseUrl(): string {
  const env = import.meta.env.VITE_API_BASE_URL;
  if (typeof env === "string" && env.length > 0) {
    return env;
  }
  if (typeof window !== "undefined" && window.location.origin.length > 0) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8000";
}

async function requestJson<T>(baseUrl: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData = init.body instanceof FormData;
  const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)/i);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (init.body !== undefined && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (sessionMatch && !headers.has(SESSION_HEADER_NAME)) {
    headers.set(SESSION_HEADER_NAME, decodeURIComponent(sessionMatch[1] ?? ""));
  }

  const response = await fetch(joinUrl(baseUrl, path), {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as unknown;
      if (isRecord(payload) && typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      detail = response.statusText || `HTTP ${response.status}`;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function createSession(baseUrl: string) {
  return requestJson<{ status: string; session_id: string }>(baseUrl, "/api/sessions", { method: "POST" });
}

export async function getApiHealth(baseUrl: string) {
  return requestJson<ApiHealthResponse>(baseUrl, "/api/health");
}

export async function getSessionSummary(baseUrl: string, sessionId: string) {
  return requestJson<SessionSummary>(baseUrl, `/api/sessions/${sessionId}`);
}

export async function getAnalysisSummary(baseUrl: string, sessionId: string) {
  return requestJson<AnalysisSummary>(baseUrl, `/api/sessions/${sessionId}/summary`);
}

export async function getSessionConfig(baseUrl: string, sessionId: string) {
  return requestJson<Record<string, unknown>>(baseUrl, `/api/sessions/${sessionId}/config`);
}

export async function updateSessionConfig(
  baseUrl: string,
  sessionId: string,
  updates: Array<{ key: string; value: unknown }>,
) {
  return requestJson<{ status: string; runconfig: Record<string, unknown>; file_path: string }>(
    baseUrl,
    `/api/sessions/${sessionId}/config`,
    {
      method: "PUT",
      body: JSON.stringify({ updates }),
    },
  );
}

export async function listDatasets(baseUrl: string) {
  return requestJson<{ datasets: SharedDatasetSummary[] }>(baseUrl, "/api/datasets");
}

export async function getDatasetPreview(baseUrl: string, datasetId: string) {
  return requestJson<DatasetPreview>(baseUrl, `/api/datasets/${datasetId}/preview`);
}

export async function uploadSharedDataset(
  baseUrl: string,
  payload: { name?: string; timeseriesFile: File; datamodelFile: File },
) {
  const formData = new FormData();
  formData.append("timeseries", payload.timeseriesFile);
  formData.append("datamodel", payload.datamodelFile);
  if (payload.name) {
    formData.append("name", payload.name);
  }
  return requestJson<Record<string, unknown>>(baseUrl, "/api/datasets", { method: "POST", body: formData });
}

export async function loadDatasetIntoSession(baseUrl: string, sessionId: string, datasetId: string) {
  return requestJson<Record<string, unknown>>(baseUrl, `/api/sessions/${sessionId}/datasets/${datasetId}/load`, {
    method: "POST",
  });
}

export async function uploadSessionFile(baseUrl: string, sessionId: string, kind: "timeseries" | "datamodel", file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<Record<string, unknown>>(baseUrl, `/api/sessions/${sessionId}/uploads/${kind}`, {
    method: "POST",
    body: formData,
  });
}

export async function getSensors(baseUrl: string, sessionId: string) {
  return requestJson<{ sensors: Array<Record<string, unknown>> }>(baseUrl, `/api/sessions/${sessionId}/sensors`);
}

export async function listScenarios(baseUrl: string, sessionId: string) {
  return requestJson<{ scenarios: ScenarioSnapshot[] }>(baseUrl, `/api/sessions/${sessionId}/scenarios`);
}

export async function saveScenario(baseUrl: string, sessionId: string, name: string) {
  return requestJson<{ status: string; scenario_index: number; name: string }>(
    baseUrl,
    `/api/sessions/${sessionId}/scenarios`,
    {
      method: "POST",
      body: JSON.stringify({ name }),
    },
  );
}

export async function deleteScenario(baseUrl: string, sessionId: string, scenarioIndex: number) {
  return requestJson<{ status: string; name: string }>(baseUrl, `/api/sessions/${sessionId}/scenarios/${scenarioIndex}`, {
    method: "DELETE",
  });
}

export async function getBrightHubStatus(baseUrl: string, sessionId: string) {
  return requestJson<BrightHubStatusResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/status`);
}

export async function loginBrightHub(
  baseUrl: string,
  sessionId: string,
  payload: { client_id: string; client_secret: string },
) {
  return requestJson<{ status: string; authenticated: boolean }>(baseUrl, `/api/sessions/${sessionId}/brighthub/login`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logoutBrightHub(baseUrl: string, sessionId: string) {
  return requestJson<{ status: string }>(baseUrl, `/api/sessions/${sessionId}/brighthub/logout`, {
    method: "POST",
  });
}

export async function listBrightHubLocations(baseUrl: string, sessionId: string) {
  return requestJson<{ locations: BrightHubLocation[] }>(baseUrl, `/api/sessions/${sessionId}/brighthub/locations`);
}

export async function importBrightHubLocation(
  baseUrl: string,
  sessionId: string,
  payload: BrightHubImportLocationPayload,
) {
  return requestJson<BrightHubImportLocationResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBrightHubReanalysisNodes(
  baseUrl: string,
  sessionId: string,
  payload: { latitude: number; longitude: number },
) {
  return requestJson<BrightHubReanalysisNodesResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/reanalysis/nodes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function downloadBrightHubReanalysis(
  baseUrl: string,
  sessionId: string,
  payload: { dataset: "ERA5" | "MERRA-2"; source?: "brighthub" | "earthdatahub"; nodes: BrightHubReanalysisNode[] },
) {
  return requestJson<BrightHubReanalysisDownloadResponse>(
    baseUrl,
    `/api/sessions/${sessionId}/brighthub/reanalysis/download`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function callSessionRoute<T>(
  baseUrl: string,
  sessionId: string,
  method: HttpMethod,
  relativePath: string,
  body?: unknown,
) {
  return requestJson<T>(baseUrl, `/api/sessions/${sessionId}${relativePath}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function getWorkflowCapabilities(baseUrl: string, sessionId: string) {
  return requestJson<{ capabilities: WorkflowDispatchCapability[] }>(
    baseUrl,
    `/api/sessions/${sessionId}/workflow/capabilities`,
  );
}

export async function executeWorkflow(baseUrl: string, sessionId: string, payload: unknown) {
  return requestJson<WorkflowExecutionResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/execute`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeWorkflowStep(baseUrl: string, sessionId: string, payload: unknown) {
  return requestJson<WorkflowExecutionResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/execute/step`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getWorkflowStatus(baseUrl: string, sessionId: string) {
  return requestJson<WorkflowExecutionStatusResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/status`);
}

export async function listWorkflowSnapshots(baseUrl: string, sessionId: string) {
  return requestJson<{ snapshots: WorkflowSnapshotSummary[] }>(baseUrl, `/api/sessions/${sessionId}/workflow/snapshots`);
}

export async function saveWorkflowSnapshot(baseUrl: string, sessionId: string, snapshotName: string, snapshot: unknown) {
  return requestJson<{ status: string; name: string; saved_at: string }>(
    baseUrl,
    `/api/sessions/${sessionId}/workflow/snapshots/${snapshotName}`,
    {
      method: "PUT",
      body: JSON.stringify({ snapshot }),
    },
  );
}

export async function loadWorkflowSnapshot(baseUrl: string, sessionId: string, snapshotName: string) {
  return requestJson<{ name: string; saved_at: string; snapshot: unknown }>(
    baseUrl,
    `/api/sessions/${sessionId}/workflow/snapshots/${snapshotName}`,
  );
}

export async function forkWorkflowBranch(baseUrl: string, sessionId: string, payload: { name?: string; from_node_id?: string }) {
  return requestJson<WorkflowForkBranchResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/branches/fork`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function compareWorkflowBranches(baseUrl: string, sessionId: string, branchSessionIds: string[]) {
  return requestJson<WorkflowCompareResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/compare`, {
    method: "POST",
    body: JSON.stringify({ branch_session_ids: branchSessionIds }),
  });
}

export async function chatSession(
  baseUrl: string,
  sessionId: string,
  payload: { api_key: string; provider: string; model: string; messages: ChatMessage[] },
) {
  return requestJson<ChatResponse>(baseUrl, `/api/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchOpenApiSpec(baseUrl: string) {
  return requestJson<Record<string, unknown>>(baseUrl, "/openapi.json");
}

export async function invokeWindKitRoute(baseUrl: string, routePath: string, payload: unknown) {
  return requestJson<WindKitResponse>(baseUrl, routePath, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}