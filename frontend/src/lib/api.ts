import { useWorkspaceStore } from "../stores/workspaceStore";
import type {
  AnalysisSummaryResponse,
  ApiHealthResponse,
  ApiStatusResponse,
  BrightHubDataModelResponse,
  DatasetEntryResponse,
  DatasetListResponse,
  DatasetLoadResponse,
  DatasetPreviewResponse,
  WorkflowExecuteRequest,
  WorkflowExecutionEvent,
  WorkflowExecutionResponse,
  WorkflowExecutionStatusResponse,
  WorkflowDispatchCapabilitiesResponse,
  WorkflowCompareRequest,
  WorkflowCompareResponse,
  WorkflowLoadSnapshotResponse,
  WorkflowForkBranchRequest,
  WorkflowForkBranchResponse,
  WorkflowSaveSnapshotResponse,
  WorkflowSnapshotListResponse,
  BrightHubImportLocationRequest,
  BrightHubImportLocationResponse,
  BrightHubLocationsResponse,
  BrightHubLoginResponse,
  BrightHubReanalysisDownloadResponse,
  BrightHubReanalysisNodesResponse,
  BrightHubStatusResponse,
  ChatRequest,
  ChatResponse,
  CleaningApplyResponse,
  CleaningLogResponse,
  ClippingAnalysisResponse,
  ConfigUpdateResponse,
  CreateSessionResponse,
  EnsembleResultsResponse,
  Era5ExtractResponse,
  Era5InterpolationResponse,
  Era5NodesResponse,
  ExtrapolationResponse,
  HomogeneityAnalysisResponse,
  HomogeneityApplyResponse,
  JsonValue,
  LtcRunResponse,
  LtcResultsResponse,
  PlotResult,
  RunConfigResponse,
  RunconfigExportResponse,
  RunScenarioRequest,
  RunScenarioResponse,
  ScenarioListResponse,
  SensorCoverageResponse,
  SensorStatisticsResponse,
  SensorsResponse,
  SessionSummaryResponse,
  SiteMapResponse,
  TableBuildResponse,
  UncertaintyResponse,
  UpdateRunConfigRequest,
} from "./types";

const API_BASE = "/api";
const SESSION_HEADER = "X-GoKaatru-Session";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function resolveSessionId(explicitSessionId?: string) {
  return explicitSessionId ?? useWorkspaceStore.getState().sessionId ?? undefined;
}

async function requestJson<T>(path: string, init: RequestInit = {}, sessionId?: string): Promise<T> {
  const headers = new Headers(init.headers);
  const resolvedSessionId = resolveSessionId(sessionId);

  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (resolvedSessionId !== undefined) {
    headers.set(SESSION_HEADER, resolvedSessionId);
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const isJson = response.headers.get("content-type")?.includes("application/json") ?? false;
  const payload = isJson ? ((await response.json()) as T | { detail?: unknown }) : await response.text();

  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : payload;
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

async function uploadFile<T>(path: string, file: File | Blob, filename: string, sessionId?: string): Promise<T> {
  const formData = new FormData();
  formData.append("file", file, filename);
  return requestJson<T>(path, { method: "POST", body: formData }, sessionId);
}

function postFormDataWithProgress<T>(
  path: string,
  formData: FormData,
  onProgress?: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`, true);
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || onProgress === undefined) {
        return;
      }
      const percent = Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100)));
      onProgress(percent);
    };

    xhr.onerror = () => {
      reject(new ApiError(0, "Network error while uploading dataset"));
    };

    xhr.onload = () => {
      const status = xhr.status;
      const payload = xhr.response ?? xhr.responseText;
      if (status < 200 || status >= 300) {
        const detail =
          typeof payload === "object" && payload !== null && "detail" in (payload as Record<string, unknown>)
            ? (payload as { detail?: unknown }).detail
            : payload;
        reject(new ApiError(status, detail));
        return;
      }
      resolve(payload as T);
    };

    xhr.send(formData);
  });
}

async function streamJsonEvents(
  path: string,
  body: unknown,
  sessionId: string,
  onEvent: (event: WorkflowExecutionEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json" });
  headers.set(SESSION_HEADER, sessionId);

  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const payload = response.headers.get("content-type")?.includes("application/json")
      ? await response.json()
      : await response.text();
    const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : payload;
    throw new ApiError(response.status, detail);
  }

  if (!response.body) {
    throw new ApiError(response.status, "Streaming response body is not available");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes("\n\n")) {
      const boundary = buffer.indexOf("\n\n");
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const dataLines = rawEvent
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .filter((line) => line.length > 0);

      if (dataLines.length === 0) {
        continue;
      }

      const merged = dataLines.join("\n");
      try {
        onEvent(JSON.parse(merged) as WorkflowExecutionEvent);
      } catch {
        // Ignore malformed event payloads and continue consuming the stream.
      }
    }
  }
}

export const healthApi = {
  get: () => requestJson<ApiHealthResponse>("/health"),
};

export const sessionsApi = {
  create: () => requestJson<CreateSessionResponse>("/sessions", { method: "POST" }),
  get: (sessionId: string) => requestJson<SessionSummaryResponse>(`/sessions/${sessionId}`, {}, sessionId),
  reset: (sessionId: string) => requestJson<SessionSummaryResponse>(`/sessions/${sessionId}/reset`, { method: "POST" }, sessionId),
  remove: (sessionId: string) => requestJson<ApiStatusResponse>(`/sessions/${sessionId}`, { method: "DELETE" }, sessionId),
};

export const uploadsApi = {
  uploadTimeseries: (sessionId: string, file: File | Blob, filename = "timeseries.csv") =>
    uploadFile<ApiStatusResponse>(`/sessions/${sessionId}/uploads/timeseries`, file, filename, sessionId),
  uploadDatamodel: (sessionId: string, file: File | Blob, filename = "datamodel.json") =>
    uploadFile<ApiStatusResponse>(`/sessions/${sessionId}/uploads/datamodel`, file, filename, sessionId),
  getSensors: (sessionId: string) => requestJson<SensorsResponse>(`/sessions/${sessionId}/sensors`, {}, sessionId),
  getCoverage: (sessionId: string, sensorName: string) =>
    requestJson<SensorCoverageResponse>(`/sessions/${sessionId}/coverage/${encodeURIComponent(sensorName)}`, {}, sessionId),
};

export const datasetsApi = {
  list: () => requestJson<DatasetListResponse>("/datasets"),
  get: (datasetId: string) => requestJson<DatasetEntryResponse>(`/datasets/${datasetId}`),
  createWithProgress: (
    options: {
      name?: string;
      timeseriesFile: File | Blob;
      datamodelFile: File | Blob;
      timeseriesFilename?: string;
      datamodelFilename?: string;
    },
    onProgress?: (percent: number) => void,
  ) => {
    const formData = new FormData();
    if (options.name && options.name.trim()) {
      formData.append("name", options.name.trim());
    }
    formData.append("timeseries", options.timeseriesFile, options.timeseriesFilename ?? "timeseries.csv");
    formData.append("datamodel", options.datamodelFile, options.datamodelFilename ?? "datamodel.json");
    return postFormDataWithProgress<DatasetEntryResponse>("/datasets", formData, onProgress);
  },
  create: (options: {
    name?: string;
    timeseriesFile: File | Blob;
    datamodelFile: File | Blob;
    timeseriesFilename?: string;
    datamodelFilename?: string;
  }) => datasetsApi.createWithProgress(options),
  remove: (datasetId: string) => requestJson<ApiStatusResponse>(`/datasets/${datasetId}`, { method: "DELETE" }),
  loadIntoSession: (sessionId: string, datasetId: string) =>
    requestJson<DatasetLoadResponse>(`/sessions/${sessionId}/datasets/${datasetId}/load`, { method: "POST" }, sessionId),
  getPreview: (datasetId: string, limit = 20) =>
    requestJson<DatasetPreviewResponse>(`/datasets/${datasetId}/preview?limit=${limit}`),
};

export const workflowApi = {
  execute: (sessionId: string, body: WorkflowExecuteRequest) =>
    requestJson<WorkflowExecutionResponse>(
      `/sessions/${sessionId}/workflow/execute`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  step: (sessionId: string, body: WorkflowExecuteRequest) =>
    requestJson<WorkflowExecutionResponse>(
      `/sessions/${sessionId}/workflow/execute/step`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  streamExecute: (
    sessionId: string,
    body: WorkflowExecuteRequest,
    onEvent: (event: WorkflowExecutionEvent) => void,
    signal?: AbortSignal,
  ) => streamJsonEvents(`/sessions/${sessionId}/workflow/execute/stream`, body, sessionId, onEvent, signal),
  getStatus: (sessionId: string) =>
    requestJson<WorkflowExecutionStatusResponse>(`/sessions/${sessionId}/workflow/status`, {}, sessionId),
  getCapabilities: (sessionId: string) =>
    requestJson<WorkflowDispatchCapabilitiesResponse>(`/sessions/${sessionId}/workflow/capabilities`, {}, sessionId),
  forkBranch: (sessionId: string, body: WorkflowForkBranchRequest) =>
    requestJson<WorkflowForkBranchResponse>(
      `/sessions/${sessionId}/workflow/branches/fork`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  compare: (sessionId: string, body: WorkflowCompareRequest) =>
    requestJson<WorkflowCompareResponse>(
      `/sessions/${sessionId}/workflow/compare`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  listSnapshots: (sessionId: string) =>
    requestJson<WorkflowSnapshotListResponse>(`/sessions/${sessionId}/workflow/snapshots`, {}, sessionId),
  saveSnapshot: (sessionId: string, name: string, snapshot: JsonValue) =>
    requestJson<WorkflowSaveSnapshotResponse>(
      `/sessions/${sessionId}/workflow/snapshots/${encodeURIComponent(name)}`,
      { method: "PUT", body: JSON.stringify({ snapshot }) },
      sessionId,
    ),
  loadSnapshot: (sessionId: string, name: string) =>
    requestJson<WorkflowLoadSnapshotResponse>(
      `/sessions/${sessionId}/workflow/snapshots/${encodeURIComponent(name)}`,
      {},
      sessionId,
    ),
  stop: (sessionId: string) =>
    requestJson<ApiStatusResponse>(`/sessions/${sessionId}/workflow/stop`, { method: "POST" }, sessionId),
};

export const configApi = {
  get: (sessionId: string) => requestJson<RunConfigResponse>(`/sessions/${sessionId}/config`, {}, sessionId),
  update: (sessionId: string, body: UpdateRunConfigRequest) =>
    requestJson<ConfigUpdateResponse>(
      `/sessions/${sessionId}/config`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
      sessionId,
    ),
  getSummary: (sessionId: string) => requestJson<AnalysisSummaryResponse>(`/sessions/${sessionId}/summary`, {}, sessionId),
};

export const analysisApi = {
  applyCleaning: (sessionId: string, body: JsonValue) =>
    requestJson<CleaningApplyResponse>(
      `/sessions/${sessionId}/cleaning/apply`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  undoCleaning: (sessionId: string, entryIndex: number) =>
    requestJson<ApiStatusResponse>(
      `/sessions/${sessionId}/cleaning/undo`,
      { method: "POST", body: JSON.stringify({ entry_index: entryIndex }) },
      sessionId,
    ),
  getCleaningLog: (sessionId: string) => requestJson<CleaningLogResponse>(`/sessions/${sessionId}/cleaning/log`, {}, sessionId),
  calculateShear: (sessionId: string, heightSensors: string) =>
    requestJson<ApiStatusResponse>(
      `/sessions/${sessionId}/shear/calculate`,
      { method: "POST", body: JSON.stringify({ height_sensors: heightSensors }) },
      sessionId,
    ),
  buildShearTable: (sessionId: string, aggregation = "mean") =>
    requestJson<TableBuildResponse>(
      `/sessions/${sessionId}/shear/table`,
      { method: "POST", body: JSON.stringify({ aggregation }) },
      sessionId,
    ),
  calculateRoughness: (sessionId: string, heightSensors: string) =>
    requestJson<ApiStatusResponse>(
      `/sessions/${sessionId}/roughness/calculate`,
      { method: "POST", body: JSON.stringify({ height_sensors: heightSensors }) },
      sessionId,
    ),
  buildRoughnessTable: (sessionId: string, aggregation = "mean") =>
    requestJson<TableBuildResponse>(
      `/sessions/${sessionId}/roughness/table`,
      { method: "POST", body: JSON.stringify({ aggregation }) },
      sessionId,
    ),
  extrapolateHub: (sessionId: string, body: JsonValue) =>
    requestJson<ExtrapolationResponse>(
      `/sessions/${sessionId}/extrapolation/hub`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  findEra5Nodes: (sessionId: string, body: JsonValue) =>
    requestJson<Era5NodesResponse>(
      `/sessions/${sessionId}/era5/nodes`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  extractEra5: (sessionId: string, body: JsonValue) =>
    requestJson<Era5ExtractResponse>(
      `/sessions/${sessionId}/era5/extract`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  interpolateEra5: (sessionId: string) =>
    requestJson<Era5InterpolationResponse>(`/sessions/${sessionId}/era5/interpolate`, { method: "POST" }, sessionId),
  runLtc: (sessionId: string, algorithm: string, body: JsonValue) =>
    requestJson<LtcRunResponse>(
      `/sessions/${sessionId}/ltc/${algorithm}`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  runEnsemble: (sessionId: string, measuredCol: string) =>
    requestJson<ApiStatusResponse>(
      `/sessions/${sessionId}/ensemble`,
      { method: "POST", body: JSON.stringify({ measured_col: measuredCol }) },
      sessionId,
    ),
  runClipping: (sessionId: string, body: JsonValue) =>
    requestJson<ClippingAnalysisResponse>(
      `/sessions/${sessionId}/clipping`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  getClippingColumns: (sessionId: string, source: string) =>
    requestJson<{ columns: string[] }>(
      `/sessions/${sessionId}/clipping/columns?source=${encodeURIComponent(source)}`,
      {},
      sessionId,
    ),
  analyzeHomogeneity: (sessionId: string, method: string) =>
    requestJson<HomogeneityAnalysisResponse>(
      `/sessions/${sessionId}/homogeneity/analyze`,
      { method: "POST", body: JSON.stringify({ method }) },
      sessionId,
    ),
  applyHomogeneity: (sessionId: string, cutoffYear: number) =>
    requestJson<HomogeneityApplyResponse>(
      `/sessions/${sessionId}/homogeneity/apply`,
      { method: "POST", body: JSON.stringify({ cutoff_year: cutoffYear }) },
      sessionId,
    ),
  calculateUncertainty: (sessionId: string, body: JsonValue) =>
    requestJson<UncertaintyResponse>(
      `/sessions/${sessionId}/uncertainty`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  getSensorStatistics: (sessionId: string, sensorName: string) =>
    requestJson<SensorStatisticsResponse>(
      `/sessions/${sessionId}/statistics/${encodeURIComponent(sensorName)}`,
      {},
      sessionId,
    ),
  saveScenario: (sessionId: string, name: string) =>
    requestJson<ApiStatusResponse>(
      `/sessions/${sessionId}/scenarios`,
      { method: "POST", body: JSON.stringify({ name }) },
      sessionId,
    ),
  listScenarios: (sessionId: string) => requestJson<ScenarioListResponse>(`/sessions/${sessionId}/scenarios`, {}, sessionId),
  deleteScenario: (sessionId: string, index: number) =>
    requestJson<ApiStatusResponse>(`/sessions/${sessionId}/scenarios/${index}`, { method: "DELETE" }, sessionId),
  importRunconfig: (sessionId: string, runconfig: Record<string, unknown>) =>
    requestJson<{ status: string; runconfig: Record<string, unknown> }>(
      `/sessions/${sessionId}/config/import`,
      { method: "POST", body: JSON.stringify({ runconfig }) },
      sessionId,
    ),
  runScenario: (sessionId: string, body: RunScenarioRequest) =>
    requestJson<RunScenarioResponse>(
      `/sessions/${sessionId}/scenarios/run`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
};

export const resultsApi = {
  getLtcResults: (sessionId: string) => requestJson<LtcResultsResponse>(`/sessions/${sessionId}/results/ltc`, {}, sessionId),
  getEnsembleResults: (sessionId: string) =>
    requestJson<EnsembleResultsResponse>(`/sessions/${sessionId}/results/ensemble`, {}, sessionId),
  getPlot: (sessionId: string, plotName: string, body: JsonValue) =>
    requestJson<PlotResult>(
      `/sessions/${sessionId}/plots/${plotName}`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
  getSiteMap: (sessionId: string) => requestJson<SiteMapResponse>(`/sessions/${sessionId}/map/site`, {}, sessionId),
  exportRunconfig: (sessionId: string) =>
    requestJson<RunconfigExportResponse>(`/sessions/${sessionId}/runconfig/export`, {}, sessionId),
};

export const exportsApi = {
  downloadTimeseries: (sessionId: string) => `${API_BASE}/sessions/${sessionId}/exports/timeseries`,
  downloadLtc: (sessionId: string, algorithm: string) => `${API_BASE}/sessions/${sessionId}/exports/ltc/${algorithm}`,
  downloadEnsemble: (sessionId: string) => `${API_BASE}/sessions/${sessionId}/exports/ensemble`,
  downloadRunconfig: (sessionId: string) => `${API_BASE}/sessions/${sessionId}/exports/runconfig`,
};

export const chatApi = {
  send: (sessionId: string, body: ChatRequest) =>
    requestJson<ChatResponse>(
      `/sessions/${sessionId}/chat`,
      { method: "POST", body: JSON.stringify(body) },
      sessionId,
    ),
};

export const brighthubApi = {
  login: (sessionId: string, clientId: string, clientSecret: string) =>
    requestJson<BrightHubLoginResponse>(
      `/sessions/${sessionId}/brighthub/login`,
      { method: "POST", body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }) },
      sessionId,
    ),
  logout: (sessionId: string) =>
    requestJson<ApiStatusResponse>(`/sessions/${sessionId}/brighthub/logout`, { method: "POST" }, sessionId),
  status: (sessionId: string) =>
    requestJson<BrightHubStatusResponse>(`/sessions/${sessionId}/brighthub/status`, {}, sessionId),
  getLocations: (sessionId: string) =>
    requestJson<BrightHubLocationsResponse>(`/sessions/${sessionId}/brighthub/locations`, {}, sessionId),
  getDataModel: (sessionId: string, uuid: string) =>
    requestJson<BrightHubDataModelResponse>(
      `/sessions/${sessionId}/brighthub/locations/${encodeURIComponent(uuid)}/datamodel`,
      {},
      sessionId,
    ),
  getReanalysisNodes: (sessionId: string, latitude: number, longitude: number) =>
    requestJson<BrightHubReanalysisNodesResponse>(
      `/sessions/${sessionId}/brighthub/reanalysis/nodes`,
      { method: "POST", body: JSON.stringify({ latitude, longitude }) },
      sessionId,
    ),
  downloadReanalysis: (sessionId: string, dataset: string, nodes: { latitude_ddeg: number; longitude_ddeg: number }[], source: string = "brighthub") =>
    requestJson<BrightHubReanalysisDownloadResponse>(
      `/sessions/${sessionId}/brighthub/reanalysis/download`,
      { method: "POST", body: JSON.stringify({ dataset, nodes, source }) },
      sessionId,
    ),
  importLocation: (sessionId: string, req: BrightHubImportLocationRequest) =>
    requestJson<BrightHubImportLocationResponse>(
      `/sessions/${sessionId}/brighthub/import`,
      { method: "POST", body: JSON.stringify(req) },
      sessionId,
    ),
};