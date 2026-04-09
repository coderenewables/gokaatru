import { useWorkspaceStore } from "../stores/workspaceStore";
import type {
  AnalysisSummaryResponse,
  ApiHealthResponse,
  ApiStatusResponse,
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