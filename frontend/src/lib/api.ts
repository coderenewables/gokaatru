// HTTP client for the GoKaatru backend.
//
// A single `requestJson` core auto-injects the `X-GoKaatru-Session` header
// by extracting the session id from the request path (spec §2.4). All endpoints
// from spec §9 are exposed as typed wrappers.
import type {
  AnalysisSummary,
  ApiHealthResponse,
  CoverageDetail,
  DatasetPreview,
  HttpMethod,
  LtcAlgorithm,
  PlotName,
  PlotRequest,
  PlotResult,
  ScenarioSnapshot,
  SensorRow,
  SensorStatistics,
  SessionSummary,
  SharedDatasetSummary,
  WorkflowDispatchCapability,
  WorkflowExecutionResponse,
  WorkflowExecutionStatusResponse,
} from "../types/analysis";

const SESSION_HEADER_NAME = "X-GoKaatru-Session";

// ---------------------------------------------------------------------------
// Response types for endpoints not yet in the core type file
// ---------------------------------------------------------------------------

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
  distance_km?: number;
  bearing?: string;
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

export interface LtcResultListResponse {
  results: Array<{
    algorithm: string;
    metrics: Record<string, unknown>;
    result_file: string | null;
    rows: number;
  }>;
}

export interface EnsembleResultResponse {
  available: boolean;
  reference_columns: string[];
  rows?: number;
  columns?: string[];
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

export interface ClippingColumnsResponse {
  columns: string[];
}

// ---------------------------------------------------------------------------
// Core request helper
// ---------------------------------------------------------------------------

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
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (init.body !== undefined && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  // Auto-inject the session header from the path (spec §1.1 / §2.4).
  const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)/i);
  if (sessionMatch && !headers.has(SESSION_HEADER_NAME)) {
    headers.set(SESSION_HEADER_NAME, decodeURIComponent(sessionMatch[1] ?? ""));
  }

  const response = await fetch(joinUrl(baseUrl, path), { ...init, headers });

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

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function getApiHealth(baseUrl: string): Promise<ApiHealthResponse> {
  return requestJson<ApiHealthResponse>(baseUrl, "/api/health");
}

// ---------------------------------------------------------------------------
// Sessions & config
// ---------------------------------------------------------------------------

export async function createSession(baseUrl: string): Promise<{ status: string; session_id: string }> {
  return requestJson(baseUrl, "/api/sessions", { method: "POST" });
}

export async function getSessionSummary(baseUrl: string, sessionId: string): Promise<SessionSummary> {
  return requestJson<SessionSummary>(baseUrl, `/api/sessions/${sessionId}`);
}

export async function resetSession(baseUrl: string, sessionId: string): Promise<SessionSummary> {
  return requestJson<SessionSummary>(baseUrl, `/api/sessions/${sessionId}/reset`, { method: "POST" });
}

export async function deleteSession(baseUrl: string, sessionId: string): Promise<void> {
  await requestJson(baseUrl, `/api/sessions/${sessionId}`, { method: "DELETE" });
}

export async function getAnalysisSummary(baseUrl: string, sessionId: string): Promise<AnalysisSummary> {
  return requestJson<AnalysisSummary>(baseUrl, `/api/sessions/${sessionId}/summary`);
}

export async function getSessionConfig(baseUrl: string, sessionId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(baseUrl, `/api/sessions/${sessionId}/config`);
}

export async function updateSessionConfig(
  baseUrl: string,
  sessionId: string,
  updates: Array<{ key: string; value: unknown }>,
): Promise<{ status: string; runconfig: Record<string, unknown>; file_path: string }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/config`, {
    method: "PUT",
    body: JSON.stringify({ updates }),
  });
}

export async function importRunconfig(
  baseUrl: string,
  sessionId: string,
  runconfig: Record<string, unknown>,
): Promise<{ status: string; runconfig: Record<string, unknown> }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/config/import`, {
    method: "POST",
    body: JSON.stringify({ runconfig }),
  });
}

// ---------------------------------------------------------------------------
// Data (Stage 1)
// ---------------------------------------------------------------------------

export async function getSensors(baseUrl: string, sessionId: string): Promise<{ sensors: SensorRow[] }> {
  return requestJson<{ sensors: SensorRow[] }>(baseUrl, `/api/sessions/${sessionId}/sensors`);
}

export async function getCoverage(baseUrl: string, sessionId: string, sensorName: string): Promise<CoverageDetail> {
  return requestJson<CoverageDetail>(baseUrl, `/api/sessions/${sessionId}/coverage/${encodeURIComponent(sensorName)}`);
}

export async function uploadSessionFile(
  baseUrl: string,
  sessionId: string,
  kind: "timeseries" | "datamodel",
  file: File,
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson(baseUrl, `/api/sessions/${sessionId}/uploads/${kind}`, {
    method: "POST",
    body: formData,
  });
}

// Shared dataset pool

export async function listDatasets(baseUrl: string): Promise<{ datasets: SharedDatasetSummary[] }> {
  return requestJson<{ datasets: SharedDatasetSummary[] }>(baseUrl, "/api/datasets");
}

export async function getDatasetPreview(baseUrl: string, datasetId: string, limit = 20): Promise<DatasetPreview> {
  return requestJson<DatasetPreview>(baseUrl, `/api/datasets/${datasetId}/preview?limit=${limit}`);
}

export async function uploadSharedDataset(
  baseUrl: string,
  payload: { name?: string; timeseriesFile: File; datamodelFile: File },
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append("timeseries", payload.timeseriesFile);
  formData.append("datamodel", payload.datamodelFile);
  if (payload.name) {
    formData.append("name", payload.name);
  }
  return requestJson(baseUrl, "/api/datasets", { method: "POST", body: formData });
}

export async function loadDatasetIntoSession(
  baseUrl: string,
  sessionId: string,
  datasetId: string,
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/datasets/${datasetId}/load`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// BrightHub (Stage 1 & 2)
// ---------------------------------------------------------------------------

export async function getBrightHubStatus(baseUrl: string, sessionId: string): Promise<BrightHubStatusResponse> {
  return requestJson<BrightHubStatusResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/status`);
}

export async function loginBrightHub(
  baseUrl: string,
  sessionId: string,
  payload: { client_id: string; client_secret: string },
): Promise<{ status: string; authenticated: boolean }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/brighthub/login`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function logoutBrightHub(baseUrl: string, sessionId: string): Promise<{ status: string }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/brighthub/logout`, { method: "POST" });
}

export async function listBrightHubLocations(
  baseUrl: string,
  sessionId: string,
): Promise<{ locations: BrightHubLocation[] }> {
  return requestJson<{ locations: BrightHubLocation[] }>(baseUrl, `/api/sessions/${sessionId}/brighthub/locations`);
}

export async function getBrightHubDataModel(
  baseUrl: string,
  sessionId: string,
  uuid: string,
): Promise<{ uuid: string; data_model: Record<string, unknown> }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/brighthub/locations/${uuid}/datamodel`);
}

export async function importBrightHubLocation(
  baseUrl: string,
  sessionId: string,
  payload: BrightHubImportLocationPayload,
): Promise<BrightHubImportLocationResponse> {
  return requestJson<BrightHubImportLocationResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchBrightHubReanalysisNodes(
  baseUrl: string,
  sessionId: string,
  payload: { latitude: number; longitude: number },
): Promise<BrightHubReanalysisNodesResponse> {
  return requestJson<BrightHubReanalysisNodesResponse>(baseUrl, `/api/sessions/${sessionId}/brighthub/reanalysis/nodes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function downloadBrightHubReanalysis(
  baseUrl: string,
  sessionId: string,
  payload: {
    dataset: "ERA5" | "MERRA-2";
    source?: "brighthub" | "earthdatahub";
    nodes: BrightHubReanalysisNode[];
  },
): Promise<BrightHubReanalysisDownloadResponse> {
  return requestJson<BrightHubReanalysisDownloadResponse>(
    baseUrl,
    `/api/sessions/${sessionId}/brighthub/reanalysis/download`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

// ---------------------------------------------------------------------------
// Direct ERA5 (Stage 2)
// ---------------------------------------------------------------------------

export async function findEra5Nodes(
  baseUrl: string,
  sessionId: string,
  payload: { latitude: number; longitude: number },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/era5/nodes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function extractEra5(
  baseUrl: string,
  sessionId: string,
  payload: { latitude: number; longitude: number; start_date: string; end_date: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/era5/extract`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function interpolateEra5(baseUrl: string, sessionId: string): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/era5/interpolate`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Shear & extrapolation (Stages 4 & 5)
// ---------------------------------------------------------------------------

export async function calculateShear(
  baseUrl: string,
  sessionId: string,
  payload: { height_sensors: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/shear/calculate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function buildShearTable(
  baseUrl: string,
  sessionId: string,
  payload: { aggregation: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/shear/table`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function calculateRoughness(
  baseUrl: string,
  sessionId: string,
  payload: { height_sensors: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/roughness/calculate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function buildRoughnessTable(
  baseUrl: string,
  sessionId: string,
  payload: { aggregation: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/roughness/table`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function extrapolateToHub(
  baseUrl: string,
  sessionId: string,
  payload: { hub_height_m: number; shear_model: "power_law" | "log_law" },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/extrapolation/hub`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Statistics & plots (Stages 3, 6, 8)
// ---------------------------------------------------------------------------

export async function getStatistics(
  baseUrl: string,
  sessionId: string,
  sensorName: string,
): Promise<SensorStatistics> {
  return requestJson<SensorStatistics>(baseUrl, `/api/sessions/${sessionId}/statistics/${encodeURIComponent(sensorName)}`);
}

export async function fetchPlot(
  baseUrl: string,
  sessionId: string,
  plotName: PlotName,
  params: PlotRequest,
): Promise<PlotResult> {
  return requestJson<PlotResult>(baseUrl, `/api/sessions/${sessionId}/plots/${plotName}`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function getSiteMap(baseUrl: string, sessionId: string): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/map/site`);
}

// ---------------------------------------------------------------------------
// Homogeneity (Stage 2)
// ---------------------------------------------------------------------------

export async function analyzeHomogeneity(
  baseUrl: string,
  sessionId: string,
  payload: { method: "annual" | "monthly" },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/homogeneity/analyze`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function applyHomogeneityCutoff(
  baseUrl: string,
  sessionId: string,
  payload: { cutoff_year: number },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/homogeneity/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// LTC, ensemble, clipping, uncertainty (Stages 6–8)
// ---------------------------------------------------------------------------

export async function runLtc(
  baseUrl: string,
  sessionId: string,
  algorithm: LtcAlgorithm,
  payload: { short_col: string; long_col: string; short_dir_col?: string; long_dir_col?: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/ltc/${algorithm}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runEnsemble(
  baseUrl: string,
  sessionId: string,
  payload: { measured_col: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/ensemble`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runClipping(
  baseUrl: string,
  sessionId: string,
  payload: { speed_col: string; source: string },
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/clipping`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getClippingColumns(
  baseUrl: string,
  sessionId: string,
  source: string,
): Promise<ClippingColumnsResponse> {
  return requestJson<ClippingColumnsResponse>(
    baseUrl,
    `/api/sessions/${sessionId}/clipping/columns?source=${encodeURIComponent(source)}`,
  );
}

export async function runUncertainty(
  baseUrl: string,
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/uncertainty`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getLtcResults(baseUrl: string, sessionId: string): Promise<LtcResultListResponse> {
  return requestJson<LtcResultListResponse>(baseUrl, `/api/sessions/${sessionId}/results/ltc`);
}

export async function getEnsembleResult(baseUrl: string, sessionId: string): Promise<EnsembleResultResponse> {
  return requestJson<EnsembleResultResponse>(baseUrl, `/api/sessions/${sessionId}/results/ensemble`);
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

export async function listScenarios(baseUrl: string, sessionId: string): Promise<{ scenarios: ScenarioSnapshot[] }> {
  return requestJson<{ scenarios: ScenarioSnapshot[] }>(baseUrl, `/api/sessions/${sessionId}/scenarios`);
}

export async function saveScenario(
  baseUrl: string,
  sessionId: string,
  name: string,
): Promise<{ status: string; scenario_index: number; name: string }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/scenarios`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function deleteScenario(
  baseUrl: string,
  sessionId: string,
  scenarioIndex: number,
): Promise<{ status: string; name: string }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/scenarios/${scenarioIndex}`, { method: "DELETE" });
}

export async function runScenario(
  baseUrl: string,
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/scenarios/run`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Workflow execution
// ---------------------------------------------------------------------------

export async function executeWorkflow(
  baseUrl: string,
  sessionId: string,
  payload: unknown,
): Promise<WorkflowExecutionResponse> {
  return requestJson<WorkflowExecutionResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/execute`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeWorkflowStep(
  baseUrl: string,
  sessionId: string,
  payload: unknown,
): Promise<WorkflowExecutionResponse> {
  return requestJson<WorkflowExecutionResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/execute/step`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getWorkflowStatus(
  baseUrl: string,
  sessionId: string,
): Promise<WorkflowExecutionStatusResponse> {
  return requestJson<WorkflowExecutionStatusResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/status`);
}

export async function stopWorkflow(
  baseUrl: string,
  sessionId: string,
): Promise<{ status: string; run_id: string | null; is_running: boolean }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/workflow/stop`, { method: "POST" });
}

export async function getWorkflowCapabilities(
  baseUrl: string,
  sessionId: string,
): Promise<{ capabilities: WorkflowDispatchCapability[] }> {
  return requestJson<{ capabilities: WorkflowDispatchCapability[] }>(
    baseUrl,
    `/api/sessions/${sessionId}/workflow/capabilities`,
  );
}

export async function listWorkflowSnapshots(
  baseUrl: string,
  sessionId: string,
): Promise<{ snapshots: WorkflowSnapshotSummary[] }> {
  return requestJson<{ snapshots: WorkflowSnapshotSummary[] }>(baseUrl, `/api/sessions/${sessionId}/workflow/snapshots`);
}

export async function saveWorkflowSnapshot(
  baseUrl: string,
  sessionId: string,
  snapshotName: string,
  snapshot: unknown,
): Promise<{ status: string; name: string; saved_at: string }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/workflow/snapshots/${snapshotName}`, {
    method: "PUT",
    body: JSON.stringify({ snapshot }),
  });
}

export async function loadWorkflowSnapshot(
  baseUrl: string,
  sessionId: string,
  snapshotName: string,
): Promise<{ name: string; saved_at: string; snapshot: unknown }> {
  return requestJson(baseUrl, `/api/sessions/${sessionId}/workflow/snapshots/${snapshotName}`);
}

export async function forkWorkflowBranch(
  baseUrl: string,
  sessionId: string,
  payload: { name?: string; from_node_id?: string },
): Promise<WorkflowForkBranchResponse> {
  return requestJson<WorkflowForkBranchResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/branches/fork`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function compareWorkflowBranches(
  baseUrl: string,
  sessionId: string,
  branchSessionIds: string[],
): Promise<WorkflowCompareResponse> {
  return requestJson<WorkflowCompareResponse>(baseUrl, `/api/sessions/${sessionId}/workflow/compare`, {
    method: "POST",
    body: JSON.stringify({ branch_session_ids: branchSessionIds }),
  });
}

// ---------------------------------------------------------------------------
// Chat (Copilot, Phase G)
// ---------------------------------------------------------------------------

export async function chatSession(
  baseUrl: string,
  sessionId: string,
  payload: { api_key: string; provider: string; model: string; messages: ChatMessage[] },
): Promise<ChatResponse> {
  return requestJson<ChatResponse>(baseUrl, `/api/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Generic session-route caller (the runStage primitive, spec §3.2)
// ---------------------------------------------------------------------------

export async function callSessionRoute<T>(
  baseUrl: string,
  sessionId: string,
  method: HttpMethod,
  relativePath: string,
  body?: unknown,
): Promise<T> {
  return requestJson<T>(baseUrl, `/api/sessions/${sessionId}${relativePath}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// OpenAPI + WindKit (Phase G)
// ---------------------------------------------------------------------------

export async function fetchOpenApiSpec(baseUrl: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(baseUrl, "/openapi.json");
}

export interface WindKitResponse {
  status: string;
  result: unknown;
}

export async function invokeWindKitRoute(
  baseUrl: string,
  routePath: string,
  payload: unknown,
): Promise<WindKitResponse> {
  return requestJson<WindKitResponse>(baseUrl, routePath, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
