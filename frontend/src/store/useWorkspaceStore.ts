// Global workspace store (spec §3.2). Single Zustand store = entire app state.
//
// Phase A includes the full state shape + the session bootstrap / refresh /
// config / plot primitives. Stage-specific orchestrators (runStage per stage)
// are layered on top of `invokeSessionOperation` in Phases D–E.
import { create } from "zustand";

import {
  type AnalysisSummary,
  type ActivityEntry,
  type AtmosphericConditionsSummary,
  type EnergyMetricsSummary,
  type ExtremeWindSummary,
  type MastEffectsSummary,
  type McpReadinessSummary,
  type OverviewSummary,
  type PersistenceSummary,
  type QcDiagnosticsSummary,
  type RampSummary,
  type SensorComparisonSummary,
  type DatasetPreview,
  type EraNode,
  type HttpMethod,
  type HomogeneityDataset,
  type LtcResultSummary,
  type ClippingReport,
  type CoverageDetail,
  type PlotName,
  type PlotRequest,
  type PlotResult,
  type SensorStatistics,
  type ScenarioSnapshot,
  type SensorRow,
  type SessionSummary,
  type SharedDatasetSummary,
  type StageId,
  type StageStatus,
  type UncertaintyResult,
  type WindAnalysisConfig,
  type WindClimateSummary,
  type TurbulenceSummary,
  type VerticalStructureSummary,
  type WorkflowDispatchCapability,
  type WorkflowExecutionStatusResponse,
} from "../types/analysis";
import {
  buildConfigAsset,
  buildDatasetPreviewAsset,
  buildOperationResultAsset,
  buildSensorInventoryAsset,
  buildSummaryAsset,
  type NormalizedAsset,
  upsertAssets,
} from "../lib/normalization";
import {
  callSessionRoute,
  createSession,
  deleteSession,
  downloadBrightHubReanalysis,
  downloadRunconfig,
  fetchBrightHubReanalysisNodes,
  fetchPlot,
  getAnalysisSummary,
  getApiHealth,
  getBrightHubStatus,
  getCoverage,
  getDatasetPreview,
  getEnsembleResult,
  getLtcResults,
  getSiteMap,
  analyzeHomogeneity,
  applyHomogeneityCutoff as applyHomogeneityCutoffApi,
  applyCleaningRule,
  undoCleaningRule,
  getCleaningLog,
  getStatistics,
  getAtmosphericConditions,
  getEnergyMetrics,
  getExtremeWinds,
  getMastEffects,
  getMcpReadiness,
  getOverviewSummary,
  getQcDiagnostics,
  getSensorComparison,
  getTurbulenceAnalysis,
  getVerticalStructure,
  getWindPersistence,
  getWindRamps,
  getWindClimate,
  getSessionConfig,
  getSessionSummary,
  getSensors,
  getWorkflowCapabilities,
  importBrightHubLocation,
  listBrightHubLocations,
  listDatasets,
  listScenarios,
  loadDatasetIntoSession,
  loginBrightHub,
  logoutBrightHub,
  runClipping,
  runEnsemble,
  runLtc,
  runUncertainty,
  saveScenario,
  deleteScenario,
  getClippingColumns,
  executeWorkflowStep as apiExecuteWorkflowStep,
  streamWorkflowExecution,
  getWorkflowStatus as apiGetWorkflowStatus,
  stopWorkflow as apiStopWorkflow,
  listWorkflowSnapshots as apiListSnapshots,
  saveWorkflowSnapshot as apiSaveSnapshot,
  loadWorkflowSnapshot as apiLoadSnapshot,
  forkWorkflowBranch as apiForkBranch,
  replaceWorkflowRunConfig as apiReplaceWorkflowRunConfig,
  listWorkflowRuns as apiListWorkflowRuns,
  compareWorkflowRuns as apiCompareWorkflowRuns,
  compareWorkflowBranches,
  uploadSessionFile as apiUploadSessionFile,
  type BrightHubLocation,
  type BrightHubStatusResponse,
  type EnsembleResultResponse,
  type LtcResultListResponse,
  resetSession,
  updateSessionConfig,
} from "../lib/api";
import {
  buildRunconfigUpdates,
  hydrateConfigFromRunconfig,
  serializeConfigToRunconfig,
  setConfigValue,
} from "../lib/configSync";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { buildDefaultWorkflowConfig, defaultWorkflowPlanKey } from "../lib/defaultWorkflowPlan";
import { computeStageStatuses } from "../lib/stages";
import {
  createWorkflowGraph,
  toExecutionRequest,
  type WorkflowCanvasNode,
  type WorkflowCanvasEdge,
} from "../lib/workflow";
import {
  readChatSettings,
  writeChatSettings,
  streamCopilotReply,
  type CopilotMessage,
  type CopilotSettings,
  type CopilotToolEvent,
} from "../lib/copilotAgent";

const ACTIVE_SESSION_STORAGE_KEY = "gokaatru-active-session-id";

type TabId = "import" | "setup" | "workflow" | "results" | "copilot" | "compare" | "howto" | "sensor_review";

interface ActivePlot {
  plotName: PlotName;
  params: PlotRequest;
  result: PlotResult;
}

interface WorkspaceStore {
  // session + bootstrap
  apiBaseUrl: string;
  apiReachable: boolean | null;
  session: SessionSummary | null;
  sessionStatus: "idle" | "loading" | "ready" | "error";
  sessionError: string | null;
  busyLabel: string | null;
  brighthubPromptRequired: boolean;
  activeTab: TabId;
  selectedStage: StageId;

  // config + summary
  config: WindAnalysisConfig;
  serverRunconfig: Record<string, unknown>;
  summary: AnalysisSummary | null;

  // shared data
  sensors: SensorRow[];
  capabilities: WorkflowDispatchCapability[];
  scenarios: ScenarioSnapshot[];

  // stage-derived state
  stageStatuses: Record<StageId, StageStatus>;
  datasets: SharedDatasetSummary[];
  datasetPreview: DatasetPreview | null;
  era5Nodes: EraNode[];
  merraNodes: EraNode[];
  ltcResults: LtcResultSummary[];
  ensembleSummary: EnsembleResultResponse | null;
  homogeneityReport: HomogeneityDataset[] | null;
  clippingReport: ClippingReport | null;
  clippingColumns: string[];
  uncertaintyResult: UncertaintyResult | null;
  brighthubStatus: BrightHubStatusResponse | null;
  brighthubLocations: import("../lib/api").BrightHubLocation[];
  brighthubReanalysis: import("../lib/api").BrightHubReanalysisNodesResponse | null;
  siteMap: Record<string, unknown> | null;
  sensorStatistics: SensorStatistics | null;
  coverageDetail: CoverageDetail | null;
  activePlot: ActivePlot | null;
  assets: NormalizedAsset[];
  activity: ActivityEntry[];

  // workflow canvas (Phase F)
  workflowNodes: WorkflowCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
  workflowStatus: WorkflowExecutionStatusResponse | null;
  workflowSnapshots: import("../lib/api").WorkflowSnapshotSummary[];
  workflowRuns: import("../lib/api").WorkflowRunSummary[];
  selectedWorkflowRunIds: string[];
  workflowRunComparison: import("../lib/api").WorkflowRunCompareResponse | null;
  defaultWorkflowStatus: "idle" | "preparing" | "ready" | "error";

  // copilot + compare (Phase G)
  chatSettings: CopilotSettings;
  chatMessages: CopilotMessage[];
  compareResult: import("../lib/api").WorkflowCompareResponse | null;
  compareSlotNames: (string | null)[];

  // actions
  setActiveTab: (tab: TabId) => void;
  setSelectedStage: (stage: StageId) => void;
  setApiBaseUrl: (url: string) => void;
  pingApi: () => Promise<void>;
  updateConfigValue: (path: string, value: unknown) => void;
  resetConfig: () => void;
  bootstrapSession: () => Promise<void>;
  newSession: () => Promise<void>;
  restoreSession: () => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  resetCurrentSession: () => Promise<void>;
  deleteCurrentSession: () => Promise<void>;
  downloadConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
  saveConfigAndRunModel: () => Promise<void>;
  fetchPlot: (plotName: PlotName, params: PlotRequest) => Promise<PlotResult>;
  refreshResults: () => Promise<void>;
  invokeSessionOperation: <T>(
    label: string,
    method: HttpMethod,
    path: string,
    body?: unknown,
  ) => Promise<T>;

  // Stage 1 — data loading
  uploadSessionFile: (kind: "timeseries" | "datamodel", file: File) => Promise<void>;
  deleteSensors: (sensorNames: string[]) => Promise<void>;
  refreshDatasets: () => Promise<void>;
  previewDataset: (datasetId: string) => Promise<void>;
  loadDataset: (datasetId: string) => Promise<void>;
  refreshBrightHub: () => Promise<void>;
  loginBrightHub: (credentials: { clientId: string; clientSecret: string }) => Promise<void>;
  logoutBrightHub: () => Promise<void>;
  importBrightHubLocation: (payload: import("../lib/api").BrightHubImportLocationPayload) => Promise<void>;

  // Stage 2 — reanalysis
  fetchBrightHubReanalysisNodes: (payload: { latitude: number; longitude: number }) => Promise<void>;
  downloadBrightHubReanalysis: (payload: {
    dataset: "ERA5" | "MERRA-2";
    source?: "brighthub" | "earthdatahub";
    useNodes: "era5" | "merra2";
  }) => Promise<void>;
  loadSiteMap: () => Promise<void>;
  runHomogeneity: (method: "annual" | "monthly") => Promise<void>;
  applyHomogeneityCutoff: (cutoffYear: number) => Promise<void>;

  // Stage 2 — cleaning
  applyCleaning: (payload: import("../lib/api").CleaningRuleRequest) => Promise<Record<string, unknown>>;
  undoCleaning: (entryIndex: number) => Promise<void>;
  refreshCleaningLog: () => Promise<import("../lib/api").CleaningLogEntry[]>;

  // Stage 3 — exploration
  loadSensorStatistics: (sensorName: string) => Promise<import("../types/analysis").SensorStatistics>;
  loadCoverage: (sensorName: string) => Promise<import("../types/analysis").CoverageDetail>;
  loadWindClimate: (speedSensor: string, directionSensor?: string) => Promise<WindClimateSummary>;
  loadVerticalStructure: (speedSensors: string, directionSensors: string) => Promise<VerticalStructureSummary>;
  loadTurbulenceAnalysis: (speedSensor: string) => Promise<TurbulenceSummary>;
  loadAtmosphericConditions: (temperatureSensor: string, pressureSensor: string, humiditySensor?: string) => Promise<AtmosphericConditionsSummary>;
  loadEnergyMetrics: (speedSensor: string, directionSensor?: string) => Promise<EnergyMetricsSummary>;
  loadExtremeWinds: (speedSensor: string) => Promise<ExtremeWindSummary>;
  loadWindRamps: (speedSensor: string) => Promise<RampSummary>;
  loadWindPersistence: (speedSensor: string) => Promise<PersistenceSummary>;
  loadSensorComparison: (sensorA?: string, sensorB?: string) => Promise<SensorComparisonSummary>;
  loadMastEffects: (sensorA?: string, sensorB?: string, directionSensor?: string) => Promise<MastEffectsSummary>;
  loadQcDiagnostics: () => Promise<QcDiagnosticsSummary>;
  loadMcpReadiness: (speedSensor: string, referenceSensor?: string) => Promise<McpReadinessSummary>;
  loadOverviewSummary: (speedSensor?: string, directionSensor?: string) => Promise<OverviewSummary>;

  // Stage 6 — LTC
  runLtcAlgorithms: (payload: {
    algorithms: import("../types/analysis").LtcAlgorithm[];
    shortCol: string;
    longCol: string;
    shortDirCol?: string;
    longDirCol?: string;
  }) => Promise<void>;

  // Stage 7 — clipping
  loadClippingColumns: (source: string) => Promise<string[]>;
  runClippingAnalysis: (payload: { speed_col: string; source: string }) => Promise<void>;

  // Stage 8 — ensemble & uncertainty
  runEnsembleAnalysis: (measuredCol: string) => Promise<void>;
  runUncertaintyAnalysis: (payload: Record<string, unknown>) => Promise<void>;
  saveScenarioSnapshot: (name: string) => Promise<void>;
  deleteScenarioSnapshot: (scenarioIndex: number) => Promise<void>;

  // Phase F — workflow canvas
  setWorkflowGraph: (nodes: WorkflowCanvasNode[], edges: WorkflowCanvasEdge[]) => void;
  prepareDefaultWorkflow: () => Promise<void>;
  rebuildWorkflowGraph: () => Promise<void>;
  executeWorkflowGraph: (mode: "auto" | "manual") => Promise<void>;
  stopWorkflowGraph: () => Promise<void>;
  refreshWorkflowStatus: () => Promise<void>;
  refreshWorkflowSnapshots: () => Promise<void>;
  saveWorkflowSnapshot: (name: string) => Promise<void>;
  loadWorkflowSnapshot: (name: string) => Promise<void>;
  forkWorkflowBranch: (name: string, fromNodeId?: string) => Promise<void>;
  replaceWorkflowRunConfig: (runconfig: Record<string, unknown>) => Promise<boolean>;
  refreshWorkflowRuns: () => Promise<void>;
  setSelectedWorkflowRunIds: (runIds: string[]) => void;
  compareWorkflowRuns: () => Promise<void>;

  // Phase G — copilot / compare
  setChatSettings: (settings: CopilotSettings) => void;
  sendChatMessage: (content: string) => Promise<void>;
  setCompareSlot: (slotIndex: number, scenarioName: string | null) => void;
  runCompare: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function createId(prefix: string): string {
  const suffix =
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}-${suffix}`;
}

function asErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function appendActivity(
  activity: ActivityEntry[],
  label: string,
  status: ActivityEntry["status"],
  detail: string,
): ActivityEntry[] {
  const entry: ActivityEntry = {
    id: createId("activity"),
    label,
    status,
    detail,
    timestamp: new Date().toISOString(),
  };
  return [entry, ...activity].slice(0, 50);
}

function readStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    return raw && raw.trim().length > 0 ? raw : null;
  } catch {
    return null;
  }
}

function writeStoredSessionId(sessionId: string | null): void {
  if (typeof window === "undefined") return;
  if (!sessionId) {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
}

function emptyStageStatuses(): Record<StageId, StageStatus> {
  return computeStageStatuses([]);
}

function toLtcResultSummaries(payload: LtcResultListResponse): LtcResultSummary[] {
  return payload.results.map((item) => ({
    algorithm: item.algorithm,
    metrics: { algorithm: item.algorithm, ...(item.metrics as Record<string, unknown>) },
    result_file: item.result_file,
    rows: item.rows,
  }));
}

/** Session facts used to fill canvas node params that the config leaves blank. */
function graphContextFromState(state: {
  sensors: SensorRow[];
  ltcResults: LtcResultSummary[];
}): { speedSensors: string[]; directionSensors: string[]; ltcAlgorithms: string[] } {
  return {
    speedSensors: state.sensors
      .filter((s) => s.sensor_type === "wind_speed")
      .sort((a, b) => a.height_m - b.height_m)
      .map((s) => s.name),
    directionSensors: state.sensors
      .filter((s) => s.sensor_type === "wind_direction")
      .sort((a, b) => a.height_m - b.height_m)
      .map((s) => s.name),
    ltcAlgorithms: state.ltcResults.map((r) => r.algorithm),
  };
}

// ---------------------------------------------------------------------------
// store
// ---------------------------------------------------------------------------

export const useWorkspaceStore = create<WorkspaceStore>((set, get) => ({
  apiBaseUrl: deriveApiBaseUrl(),
  apiReachable: null,
  session: null,
  sessionStatus: "idle",
  sessionError: null,
  busyLabel: null,
  brighthubPromptRequired: false,
  activeTab: "import",
  selectedStage: "cleaning",

  config: createDefaultWindAnalysisConfig(),
  serverRunconfig: {},
  summary: null,

  sensors: [],
  capabilities: [],
  scenarios: [],

  stageStatuses: emptyStageStatuses(),
  datasets: [],
  datasetPreview: null,
  era5Nodes: [],
  merraNodes: [],
  ltcResults: [],
  ensembleSummary: null,
  homogeneityReport: null,
  clippingReport: null,
  clippingColumns: [],
  uncertaintyResult: null,
  brighthubStatus: null,
  brighthubLocations: [],
  brighthubReanalysis: null,
  siteMap: null,
  sensorStatistics: null,
  coverageDetail: null,
  activePlot: null,
  assets: [buildConfigAsset(createDefaultWindAnalysisConfig())],
  activity: [],

  workflowNodes: [],
  workflowEdges: [],
  workflowStatus: null,
  workflowSnapshots: [],
  workflowRuns: [],
  selectedWorkflowRunIds: [],
  workflowRunComparison: null,
  defaultWorkflowStatus: "idle",

  chatSettings: readChatSettings(),
  chatMessages: [],
  compareResult: null,
  compareSlotNames: ["baseline", null, null],

  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedStage: (stage) => set({ selectedStage: stage }),

  setApiBaseUrl: (url) => set({ apiBaseUrl: url, apiReachable: null }),

  pingApi: async () => {
    try {
      await getApiHealth(get().apiBaseUrl);
      set({ apiReachable: true });
    } catch (error) {
      set({
        apiReachable: false,
        activity: appendActivity(get().activity, "API unreachable", "error", asErrorMessage(error)),
      });
    }
  },

  updateConfigValue: (path, value) => {
    const nextConfig = setConfigValue(get().config, path, value);
    set({
      config: nextConfig,
      assets: upsertAssets(get().assets, [buildConfigAsset(nextConfig)]),
    });
  },

  resetConfig: () =>
    set({
      config: createDefaultWindAnalysisConfig(),
      assets: upsertAssets(get().assets, [buildConfigAsset(createDefaultWindAnalysisConfig())]),
    }),

  bootstrapSession: async () => {
    if (get().sessionStatus === "loading") return;
    set({ sessionStatus: "loading", sessionError: null, busyLabel: "Creating session" });
    try {
      const created = await createSession(get().apiBaseUrl);
      const session = await getSessionSummary(get().apiBaseUrl, created.session_id);
      writeStoredSessionId(session.session_id);
      set({ session, sessionStatus: "ready", busyLabel: null });
      await get().refreshWorkspace();
      await get().refreshWorkflowRuns();
      set({
        activity: appendActivity(get().activity, "Created session", "ok", session.session_id),
      });
    } catch (error) {
      set({
        sessionStatus: "error",
        sessionError: asErrorMessage(error),
        busyLabel: null,
        activity: appendActivity(get().activity, "Failed to create session", "error", asErrorMessage(error)),
      });
    }
  },

  newSession: async () => {
    // Start a fresh session: delete the current one (backend removes its
    // workspace directory) and clear all local state before bootstrapping.
    const existing = get().session;
    if (existing) {
      await get().deleteCurrentSession();
      // Bail out if the delete failed and the session is still active.
      if (get().session !== null) return;
    }
    writeStoredSessionId(null);
    set({
      config: createDefaultWindAnalysisConfig(),
      serverRunconfig: {},
      assets: [buildConfigAsset(createDefaultWindAnalysisConfig())],
      chatMessages: [],
      compareResult: null,
      compareSlotNames: ["baseline", null, null],
      activeTab: "import",
      selectedStage: "cleaning",
      workflowNodes: [],
      workflowEdges: [],
      defaultWorkflowStatus: "idle",
    });
    await get().bootstrapSession();
  },

  restoreSession: async () => {
    if (get().session !== null || get().sessionStatus === "loading") return;
    const storedSessionId = readStoredSessionId();
    if (!storedSessionId) return;

    set({ sessionStatus: "loading", sessionError: null, busyLabel: "Restoring workspace" });
    try {
      const session = await getSessionSummary(get().apiBaseUrl, storedSessionId);
      writeStoredSessionId(session.session_id);
      set({ session, sessionStatus: "ready", busyLabel: null });
      await get().refreshWorkspace();
      set({
        activity: appendActivity(get().activity, "Restored session", "ok", session.session_id),
      });
    } catch (error) {
      writeStoredSessionId(null);
      set({
        session: null,
        sessionStatus: "idle",
        sessionError: null,
        busyLabel: null,
        activity: appendActivity(get().activity, "Saved session unavailable", "error", asErrorMessage(error)),
      });
    }
  },

  refreshWorkspace: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Refreshing workspace" });
    try {
      const [summary, runconfig, sensorsPayload, capabilitiesPayload, scenariosPayload] = await Promise.all([
        getAnalysisSummary(get().apiBaseUrl, session.session_id),
        getSessionConfig(get().apiBaseUrl, session.session_id),
        getSensors(get().apiBaseUrl, session.session_id).catch(() => ({ sensors: [] })),
        getWorkflowCapabilities(get().apiBaseUrl, session.session_id),
        listScenarios(get().apiBaseUrl, session.session_id).catch(() => ({ scenarios: [] })),
      ]);

      const nextConfig = hydrateConfigFromRunconfig(runconfig);
      const completedSteps = summary.completed_steps ?? [];
      const stageStatuses = computeStageStatuses(completedSteps);
      const scenarios = scenariosPayload.scenarios ?? [];
      const nextAssets = upsertAssets(get().assets, [
        buildConfigAsset(nextConfig),
        buildSummaryAsset(summary),
        buildSensorInventoryAsset(sensorsPayload.sensors ?? []),
      ]);
      set({
        summary,
        serverRunconfig: runconfig,
        config: nextConfig,
        sensors: sensorsPayload.sensors ?? [],
        capabilities: capabilitiesPayload.capabilities,
        scenarios,
        stageStatuses,
        assets: nextAssets,
        busyLabel: null,
      });
      // The planner is intentionally non-blocking: importing data and saving
      // the hub height can happen in either order, and the final qualifying
      // refresh seeds the editable canvas exactly once.
      void get().prepareDefaultWorkflow();
      // Best-effort workflow status + snapshots (non-fatal).
      void get().refreshWorkflowStatus();
      void get().refreshWorkflowSnapshots();
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, "Workspace refresh failed", "error", asErrorMessage(error)),
      });
    }
  },

  resetCurrentSession: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Resetting session" });
    try {
      const reset = await resetSession(get().apiBaseUrl, session.session_id);
      set({ session: reset, busyLabel: null });
      await get().refreshWorkspace();
      set({
        activity: appendActivity(get().activity, "Reset session", "ok", reset.session_id),
      });
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, "Session reset failed", "error", asErrorMessage(error)),
      });
    }
  },

  deleteCurrentSession: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Deleting session" });
    try {
      await deleteSession(get().apiBaseUrl, session.session_id);
      writeStoredSessionId(null);
      set({
        session: null,
        sessionStatus: "idle",
        summary: null,
        config: createDefaultWindAnalysisConfig(),
        serverRunconfig: {},
        sensors: [],
        scenarios: [],
        datasets: [],
        datasetPreview: null,
        era5Nodes: [],
        merraNodes: [],
        ltcResults: [],
        ensembleSummary: null,
        homogeneityReport: null,
        clippingReport: null,
        clippingColumns: [],
        uncertaintyResult: null,
        siteMap: null,
        sensorStatistics: null,
        coverageDetail: null,
        activePlot: null,
        workflowStatus: null,
        workflowNodes: [],
        workflowEdges: [],
        defaultWorkflowStatus: "idle",
        stageStatuses: emptyStageStatuses(),
        busyLabel: null,
        activeTab: "import",
        selectedStage: "cleaning",
        activity: appendActivity(get().activity, "Deleted session", "ok", session.session_id),
      });
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, "Session delete failed", "error", asErrorMessage(error)),
      });
    }
  },

  downloadConfig: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Downloading config" });
    try {
      await downloadRunconfig(get().apiBaseUrl, session.session_id);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Downloaded runconfig", "ok", "runconfig.json"),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Config download failed", "error", asErrorMessage(error)),
      }));
    }
  },

  saveConfig: async () => {
    const session = get().session;
    if (!session) return;
    const nextRunconfig = serializeConfigToRunconfig(get().config);
    const updates = buildRunconfigUpdates(get().serverRunconfig, nextRunconfig);
    if (updates.length === 0) {
      void get().prepareDefaultWorkflow();
      return;
    }

    set({ busyLabel: "Saving config" });
    try {
      const response = await updateSessionConfig(get().apiBaseUrl, session.session_id, updates);
      const nextConfig = hydrateConfigFromRunconfig(response.runconfig);
      set((state) => ({
        config: nextConfig,
        serverRunconfig: response.runconfig,
        assets: upsertAssets(state.assets, [buildConfigAsset(nextConfig)]),
        busyLabel: null,
        activity: appendActivity(
          state.activity,
          "Saved config",
          "ok",
          `${updates.length} update(s)`,
        ),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, "Config save failed", "error", asErrorMessage(error)),
      });
    }
  },

  saveConfigAndRunModel: async () => {
    const current = get();
    const session = current.session;
    if (!session) return;
    if (!current.summary?.timeseries_loaded) {
      set((state) => ({
        activity: appendActivity(state.activity, "Model run blocked", "error", "Import measurement data before running the model"),
      }));
      return;
    }
    if (!Number.isFinite(current.config.site.hubHeightM) || current.config.site.hubHeightM <= 0) {
      set((state) => ({
        activity: appendActivity(state.activity, "Model run blocked", "error", "Enter a hub height greater than zero"),
      }));
      return;
    }

    set({ busyLabel: "Checking BrightHub access" });
    try {
      const brighthubStatus = await getBrightHubStatus(get().apiBaseUrl, session.session_id);
      if (!brighthubStatus.authenticated) {
        set((state) => ({
          busyLabel: null,
          brighthubStatus,
          brighthubPromptRequired: true,
          activeTab: "import",
          activity: appendActivity(state.activity, "BrightHub credentials required", "error", "Sign in to run the default ERA5 and MERRA-2 workflow"),
        }));
        return;
      }

      const plannedConfig = buildDefaultWorkflowConfig(current.config, current.sensors);
      const updates = buildRunconfigUpdates(
        current.serverRunconfig,
        serializeConfigToRunconfig(plannedConfig),
      );
      set({ busyLabel: "Saving config" });
      const response = await updateSessionConfig(get().apiBaseUrl, session.session_id, updates);
      const savedConfig = hydrateConfigFromRunconfig(response.runconfig);
      const graph = createWorkflowGraph(savedConfig, get().capabilities, graphContextFromState(get()));
      set((state) => ({
        config: savedConfig,
        serverRunconfig: response.runconfig,
        workflowNodes: graph.nodes,
        workflowEdges: graph.edges,
        activeTab: "workflow",
        busyLabel: null,
        brighthubStatus,
        brighthubPromptRequired: false,
        defaultWorkflowStatus: "ready",
        assets: upsertAssets(state.assets, [buildConfigAsset(savedConfig)]),
        activity: appendActivity(state.activity, "Saved config and prepared model", "ok", `${graph.nodes.length} nodes`),
      }));
      await get().executeWorkflowGraph("auto");
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Save and run failed", "error", asErrorMessage(error)),
      }));
    }
  },

  fetchPlot: async (plotName, params) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    set({ busyLabel: `Rendering ${plotName}` });
    try {
      const result = await fetchPlot(get().apiBaseUrl, session.session_id, plotName, params);
      set((state) => ({
        activePlot: { plotName, params, result },
        assets: upsertAssets(state.assets, [buildOperationResultAsset(`plot:${plotName}`, result)]),
        busyLabel: null,
      }));
      return result;
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, `Plot ${plotName} failed`, "error", asErrorMessage(error)),
      });
      throw error;
    }
  },

  refreshResults: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const [ltc, ensemble] = await Promise.all([
        getLtcResults(get().apiBaseUrl, session.session_id).catch(() => null),
        getEnsembleResult(get().apiBaseUrl, session.session_id).catch(() => null),
      ]);
      set({
        ltcResults: ltc ? toLtcResultSummaries(ltc) : [],
        ensembleSummary: ensemble,
      });
    } catch (error) {
      set({
        activity: appendActivity(get().activity, "Results refresh failed", "error", asErrorMessage(error)),
      });
    }
  },

  invokeSessionOperation: async <T,>(label: string, method: HttpMethod, path: string, body?: unknown) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    set({ busyLabel: label });
    try {
      const response = await callSessionRoute<T>(get().apiBaseUrl, session.session_id, method, path, body);
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(label, response)]),
        activity: appendActivity(state.activity, label, "ok", "Operation completed"),
      }));
      await get().refreshWorkspace();
      return response;
    } catch (error) {
      set({
        busyLabel: null,
        activity: appendActivity(get().activity, label, "error", asErrorMessage(error)),
      });
      throw error;
    }
  },

  // ---- Stage 1: data loading ---------------------------------------------

  uploadSessionFile: async (kind, file) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: `Uploading ${kind}` });
    try {
      const response = await apiUploadSessionFile(get().apiBaseUrl, session.session_id, kind, file);
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(`upload-${kind}`, response)]),
        activity: appendActivity(state.activity, `Uploaded ${kind}`, "ok", file.name),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, `Failed to upload ${kind}`, "error", asErrorMessage(error)),
      }));
    }
  },

  deleteSensors: async (sensorNames) => {
    const session = get().session;
    if (!session || sensorNames.length === 0) return;
    set({ busyLabel: `Removing ${sensorNames.length} sensor(s)` });
    try {
      const { deleteSensors: apiDeleteSensors } = await import("../lib/api");
      const response = await apiDeleteSensors(get().apiBaseUrl, session.session_id, sensorNames);
      set((state) => ({
        busyLabel: null,
        sensors: state.sensors.filter((s) => !sensorNames.includes(s.name)),
        assets: upsertAssets(state.assets, [buildOperationResultAsset("sensor-delete", response)]),
        activity: appendActivity(
          state.activity,
          "Removed sensors",
          "ok",
          `${response.removed.length} removed, ${response.remaining_count} remaining`,
        ),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Sensor removal failed", "error", asErrorMessage(error)),
      }));
    }
  },

  refreshDatasets: async () => {
    try {
      const payload = await listDatasets(get().apiBaseUrl);
      set({ datasets: payload.datasets });
    } catch {
      /* non-fatal */
    }
  },

  previewDataset: async (datasetId) => {
    set({ busyLabel: "Loading dataset preview" });
    try {
      const preview = await getDatasetPreview(get().apiBaseUrl, datasetId);
      set((state) => ({
        datasetPreview: preview,
        assets: upsertAssets(state.assets, [buildDatasetPreviewAsset(datasetId, preview)]),
        busyLabel: null,
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Dataset preview failed", "error", asErrorMessage(error)),
      }));
    }
  },

  loadDataset: async (datasetId) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Loading dataset into session" });
    try {
      await loadDatasetIntoSession(get().apiBaseUrl, session.session_id, datasetId);
      // Keep the typed config in sync immediately so the stepper reflects the
      // loaded dataset and a subsequent save persists it back to runconfig.
      set((state) => ({
        config: setConfigValue(state.config, "inputs.sharedDatasetId", datasetId),
        busyLabel: null,
        activity: appendActivity(state.activity, "Loaded shared dataset", "ok", datasetId),
      }));
      await get().previewDataset(datasetId);
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to load dataset", "error", asErrorMessage(error)),
      }));
    }
  },

  refreshBrightHub: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const status = await getBrightHubStatus(get().apiBaseUrl, session.session_id);
      const locations: BrightHubLocation[] = status.authenticated
        ? (await listBrightHubLocations(get().apiBaseUrl, session.session_id).catch(() => ({ locations: [] }))).locations
        : [];
      set({ brighthubStatus: status, brighthubLocations: locations });
    } catch {
      set({ brighthubStatus: { authenticated: false, has_token: false }, brighthubLocations: [] });
    }
  },

  loginBrightHub: async ({ clientId, clientSecret }) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Connecting to BrightHub" });
    try {
      await loginBrightHub(get().apiBaseUrl, session.session_id, {
        client_id: clientId,
        client_secret: clientSecret,
      });
      set((state) => ({
        busyLabel: null,
        brighthubPromptRequired: false,
        activity: appendActivity(state.activity, "BrightHub login", "ok", "Authenticated"),
      }));
      await get().refreshBrightHub();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "BrightHub login failed", "error", asErrorMessage(error)),
      }));
    }
  },

  logoutBrightHub: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Disconnecting BrightHub" });
    try {
      await logoutBrightHub(get().apiBaseUrl, session.session_id);
      set((state) => ({
        busyLabel: null,
        brighthubStatus: { authenticated: false, has_token: false },
        brighthubLocations: [],
        activity: appendActivity(state.activity, "BrightHub logout", "ok", "Disconnected"),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "BrightHub logout failed", "error", asErrorMessage(error)),
      }));
    }
  },

  importBrightHubLocation: async (payload) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Importing BrightHub location" });
    try {
      const response = await importBrightHubLocation(get().apiBaseUrl, session.session_id, payload);
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("brighthub-import", response)]),
        activity: appendActivity(state.activity, "Imported BrightHub location", "ok", response.uuid),
      }));
      await get().refreshWorkspace();
      await get().refreshBrightHub();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "BrightHub import failed", "error", asErrorMessage(error)),
      }));
    }
  },

  // ---- Stage 2: reanalysis -----------------------------------------------

  fetchBrightHubReanalysisNodes: async (payload) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Finding reanalysis nodes" });
    try {
      const response = await fetchBrightHubReanalysisNodes(get().apiBaseUrl, session.session_id, payload);
      set((state) => ({
        brighthubReanalysis: response,
        era5Nodes: response.era5_nodes.map((n) => ({
          latitude: n.latitude_ddeg,
          longitude: n.longitude_ddeg,
          distance_km: typeof n.distance_km === "number" ? n.distance_km : undefined,
          bearing: n.bearing,
        })),
        merraNodes: response.merra2_nodes.map((n) => ({
          latitude: n.latitude_ddeg,
          longitude: n.longitude_ddeg,
          distance_km: typeof n.distance_km === "number" ? n.distance_km : undefined,
          bearing: n.bearing,
        })),
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("reanalysis-nodes", response)]),
        activity: appendActivity(
          state.activity,
          "Fetched reanalysis nodes",
          "ok",
          `${response.era5_nodes.length} ERA5 / ${response.merra2_nodes.length} MERRA-2`,
        ),
      }));
      await get().loadSiteMap();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Reanalysis node lookup failed", "error", asErrorMessage(error)),
      }));
    }
  },

  downloadBrightHubReanalysis: async ({ dataset, source, useNodes }) => {
    const session = get().session;
    const nodesPayload = get().brighthubReanalysis;
    if (!session || !nodesPayload) return;
    const nodes = useNodes === "merra2" ? nodesPayload.merra2_nodes : nodesPayload.era5_nodes;
    if (nodes.length === 0) return;
    set({ busyLabel: `Downloading ${dataset}` });
    try {
      const response = await downloadBrightHubReanalysis(get().apiBaseUrl, session.session_id, {
        dataset,
        source,
        nodes,
      });
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(`${dataset}-download`, response)]),
        activity: appendActivity(state.activity, `Downloaded ${dataset}`, "ok", `${response.items.length} node(s)`),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, `${dataset} download failed`, "error", asErrorMessage(error)),
      }));
    }
  },

  loadSiteMap: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const geojson = await getSiteMap(get().apiBaseUrl, session.session_id);
      set({ siteMap: geojson });
    } catch {
      /* non-fatal */
    }
  },

  runHomogeneity: async (method) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: `Homogeneity (${method})` });
    try {
      const response = (await analyzeHomogeneity(get().apiBaseUrl, session.session_id, { method })) as {
        datasets?: HomogeneityDataset[];
      };
      const datasets = response.datasets ?? [];
      set((state) => ({
        homogeneityReport: datasets,
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("homogeneity", response)]),
        activity: appendActivity(
          state.activity,
          `Homogeneity (${method})`,
          "ok",
          `${datasets.length} dataset(s)`,
        ),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        homogeneityReport: null,
        activity: appendActivity(state.activity, "Homogeneity failed", "error", asErrorMessage(error)),
      }));
    }
  },

  applyHomogeneityCutoff: async (cutoffYear) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Applying homogeneity cutoff" });
    try {
      const response = await applyHomogeneityCutoffApi(get().apiBaseUrl, session.session_id, {
        cutoff_year: cutoffYear,
      });
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("homogeneity-cutoff", response)]),
        activity: appendActivity(state.activity, "Applied homogeneity cutoff", "ok", `year ${cutoffYear}`),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Homogeneity cutoff failed", "error", asErrorMessage(error)),
      }));
    }
  },

  // ---- Stage 2: cleaning --------------------------------------------------

  applyCleaning: async (payload) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    set({ busyLabel: `Cleaning ${payload.sensor || "timeseries"}` });
    try {
      const result = await applyCleaningRule(get().apiBaseUrl, session.session_id, payload);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(
          state.activity,
          `Cleaning · ${payload.rule_type}`,
          "ok",
          `${String(result.records_affected ?? 0)} record(s)`,
        ),
      }));
      await get().refreshWorkspace();
      return result;
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Cleaning failed", "error", asErrorMessage(error)),
      }));
      throw error;
    }
  },

  undoCleaning: async (entryIndex) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Undoing cleaning rule" });
    try {
      await undoCleaningRule(get().apiBaseUrl, session.session_id, entryIndex);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Undid cleaning rule", "ok", `#${entryIndex}`),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Undo cleaning failed", "error", asErrorMessage(error)),
      }));
    }
  },

  refreshCleaningLog: async () => {
    const session = get().session;
    if (!session) return [];
    try {
      const result = await getCleaningLog(get().apiBaseUrl, session.session_id);
      return result.entries ?? [];
    } catch {
      return [];
    }
  },

  // ---- Stage 3: exploration ----------------------------------------------

  loadSensorStatistics: async (sensorName) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    set({ busyLabel: `Statistics for ${sensorName}` });
    try {
      const stats = await getStatistics(get().apiBaseUrl, session.session_id, sensorName);
      set({ sensorStatistics: stats, busyLabel: null });
      return stats;
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Statistics failed", "error", asErrorMessage(error)),
      }));
      throw error;
    }
  },

  loadCoverage: async (sensorName) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    set({ busyLabel: `Coverage for ${sensorName}` });
    try {
      const coverage = await getCoverage(get().apiBaseUrl, session.session_id, sensorName);
      set({ coverageDetail: coverage, busyLabel: null });
      return coverage;
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Coverage failed", "error", asErrorMessage(error)),
      }));
      throw error;
    }
  },

  loadWindClimate: async (speedSensor, directionSensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getWindClimate(get().apiBaseUrl, session.session_id, speedSensor, directionSensor);
  },

  loadVerticalStructure: async (speedSensors, directionSensors) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getVerticalStructure(get().apiBaseUrl, session.session_id, speedSensors, directionSensors);
  },

  loadTurbulenceAnalysis: async (speedSensor) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getTurbulenceAnalysis(get().apiBaseUrl, session.session_id, speedSensor);
  },

  loadAtmosphericConditions: async (temperatureSensor, pressureSensor, humiditySensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getAtmosphericConditions(get().apiBaseUrl, session.session_id, temperatureSensor, pressureSensor, humiditySensor);
  },

  loadEnergyMetrics: async (speedSensor, directionSensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getEnergyMetrics(get().apiBaseUrl, session.session_id, speedSensor, directionSensor);
  },

  loadExtremeWinds: async (speedSensor) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getExtremeWinds(get().apiBaseUrl, session.session_id, speedSensor);
  },

  loadWindRamps: async (speedSensor) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getWindRamps(get().apiBaseUrl, session.session_id, speedSensor);
  },

  loadWindPersistence: async (speedSensor) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getWindPersistence(get().apiBaseUrl, session.session_id, speedSensor);
  },

  loadSensorComparison: async (sensorA = "", sensorB = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getSensorComparison(get().apiBaseUrl, session.session_id, sensorA, sensorB);
  },

  loadMastEffects: async (sensorA = "", sensorB = "", directionSensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getMastEffects(get().apiBaseUrl, session.session_id, sensorA, sensorB, directionSensor);
  },

  loadQcDiagnostics: async () => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getQcDiagnostics(get().apiBaseUrl, session.session_id);
  },

  loadMcpReadiness: async (speedSensor, referenceSensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getMcpReadiness(get().apiBaseUrl, session.session_id, speedSensor, referenceSensor);
  },

  loadOverviewSummary: async (speedSensor = "", directionSensor = "") => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    return getOverviewSummary(get().apiBaseUrl, session.session_id, speedSensor, directionSensor);
  },

  // ---- Stage 6: LTC ------------------------------------------------------

  runLtcAlgorithms: async (payload) => {
    const session = get().session;
    if (!session) return;
    for (const algorithm of payload.algorithms) {
      set({ busyLabel: `Running LTC · ${algorithm}` });
      try {
        const result = await runLtc(get().apiBaseUrl, session.session_id, algorithm, {
          short_col: payload.shortCol,
          long_col: payload.longCol,
          short_dir_col: payload.shortDirCol,
          long_dir_col: payload.longDirCol,
        });
        set((state) => ({
          assets: upsertAssets(state.assets, [buildOperationResultAsset(`ltc:${algorithm}`, result)]),
          activity: appendActivity(state.activity, `LTC · ${algorithm}`, "ok", "Completed"),
        }));
      } catch (error) {
        set((state) => ({
          activity: appendActivity(state.activity, `LTC · ${algorithm} failed`, "error", asErrorMessage(error)),
        }));
      }
    }
    set({ busyLabel: null });
    await get().refreshResults();
    await get().refreshWorkspace();
  },

  // ---- Stage 7: clipping -------------------------------------------------

  loadClippingColumns: async (source) => {
    const session = get().session;
    if (!session) throw new Error("Session is not initialized");
    try {
      const payload = await getClippingColumns(get().apiBaseUrl, session.session_id, source);
      set({ clippingColumns: payload.columns });
      return payload.columns;
    } catch (error) {
      set((state) => ({
        activity: appendActivity(state.activity, "Clipping columns failed", "error", asErrorMessage(error)),
      }));
      return [];
    }
  },

  runClippingAnalysis: async (payload) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Clipping analysis" });
    try {
      const result = (await runClipping(
        get().apiBaseUrl,
        session.session_id,
        payload,
      )) as unknown as ClippingReport;
      set((state) => ({
        clippingReport: result,
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("clipping", result)]),
        activity: appendActivity(
          state.activity,
          "Clipping analysis",
          "ok",
          `optimal start ${result.optimal_start_year}`,
        ),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Clipping failed", "error", asErrorMessage(error)),
      }));
    }
  },

  // ---- Stage 8: ensemble & uncertainty -----------------------------------

  runEnsembleAnalysis: async (measuredCol) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Running ensemble" });
    try {
      const result = await runEnsemble(get().apiBaseUrl, session.session_id, { measured_col: measuredCol });
      set((state) => ({
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("ensemble", result)]),
        activity: appendActivity(state.activity, "Ensemble", "ok", "Blended"),
      }));
      await get().refreshResults();
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Ensemble failed", "error", asErrorMessage(error)),
      }));
    }
  },

  runUncertaintyAnalysis: async (payload) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Calculating uncertainty" });
    try {
      const result = (await runUncertainty(
        get().apiBaseUrl,
        session.session_id,
        payload,
      )) as unknown as UncertaintyResult;
      set((state) => ({
        uncertaintyResult: result,
        busyLabel: null,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("uncertainty", result)]),
        activity: appendActivity(
          state.activity,
          "Uncertainty",
          "ok",
          `${result.total_uncertainty_pct}% total`,
        ),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Uncertainty failed", "error", asErrorMessage(error)),
      }));
    }
  },

  saveScenarioSnapshot: async (name) => {
    const session = get().session;
    if (!session || name.trim().length === 0) return;
    set({ busyLabel: "Saving scenario" });
    try {
      await saveScenario(get().apiBaseUrl, session.session_id, name.trim());
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved scenario", "ok", name.trim()),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Scenario save failed", "error", asErrorMessage(error)),
      }));
    }
  },

  deleteScenarioSnapshot: async (scenarioIndex) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Deleting scenario" });
    try {
      const result = await deleteScenario(get().apiBaseUrl, session.session_id, scenarioIndex);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Deleted scenario", "ok", result.name),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Scenario delete failed", "error", asErrorMessage(error)),
      }));
    }
  },

  // ---- Phase F: workflow canvas ------------------------------------------

  setWorkflowGraph: (nodes, edges) => set({ workflowNodes: nodes, workflowEdges: edges }),

  prepareDefaultWorkflow: async () => {
    const current = get();
    const session = current.session;
    const savedHubHeight = current.serverRunconfig.hub_height_m;
    const hubHeightM =
      typeof savedHubHeight === "number"
        ? savedHubHeight
        : typeof savedHubHeight === "string"
          ? Number(savedHubHeight)
          : Number.NaN;
    const hasLoadedMeasurements = current.summary?.timeseries_loaded === true;
    const hasSpeedSensor = current.sensors.some((sensor) => sensor.sensor_type === "wind_speed");

    if (
      !session ||
      current.defaultWorkflowStatus === "preparing" ||
      !hasLoadedMeasurements ||
      !hasSpeedSensor ||
      !Number.isFinite(hubHeightM) ||
      hubHeightM <= 0
    ) {
      return;
    }

    const expectedPlanKey = defaultWorkflowPlanKey(current.config, current.sensors);
    if (current.config.workflow.defaultPlanKey === expectedPlanKey) {
      if (current.workflowNodes.length === 0) {
        const graph = createWorkflowGraph(current.config, current.capabilities, graphContextFromState(current));
        set({
          workflowNodes: graph.nodes,
          workflowEdges: graph.edges,
          defaultWorkflowStatus: "ready",
        });
      }
      return;
    }

    const plannedConfig = buildDefaultWorkflowConfig(current.config, current.sensors);
    const updates = buildRunconfigUpdates(
      current.serverRunconfig,
      serializeConfigToRunconfig(plannedConfig),
    );
    set({ busyLabel: "Preparing default workflow", defaultWorkflowStatus: "preparing" });
    try {
      const response = await updateSessionConfig(get().apiBaseUrl, session.session_id, updates);
      const persistedConfig = hydrateConfigFromRunconfig(response.runconfig);
      const graph = createWorkflowGraph(
        persistedConfig,
        get().capabilities,
        graphContextFromState(get()),
      );
      set((state) => ({
        config: persistedConfig,
        serverRunconfig: response.runconfig,
        workflowNodes: graph.nodes,
        workflowEdges: graph.edges,
        activeTab: "workflow",
        busyLabel: null,
        defaultWorkflowStatus: "ready",
        assets: upsertAssets(state.assets, [buildConfigAsset(persistedConfig)]),
        activity: appendActivity(
          state.activity,
          "Prepared default workflow",
          "ok",
          `${graph.nodes.length} nodes ready to edit and run`,
        ),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        defaultWorkflowStatus: "error",
        activity: appendActivity(state.activity, "Default workflow preparation failed", "error", asErrorMessage(error)),
      }));
    }
  },

  rebuildWorkflowGraph: async () => {
    // Rebuild the canvas from the authoritative runconfig: pull the latest
    // config from the backend, hydrate it into the store, then emit the graph.
    const session = get().session;
    set({ busyLabel: "Rebuilding canvas" });
    try {
      let nextConfig = get().config;
      if (session) {
        // Pull the authoritative runconfig plus the session facts (sensor
        // inventory, completed LTC runs) used to fill node params.
        const [runconfig, sensorsPayload, ltcPayload] = await Promise.all([
          getSessionConfig(get().apiBaseUrl, session.session_id),
          getSensors(get().apiBaseUrl, session.session_id).catch(() => ({ sensors: [] })),
          getLtcResults(get().apiBaseUrl, session.session_id).catch(() => null),
        ]);
        nextConfig = hydrateConfigFromRunconfig(runconfig);
        const sensors = (sensorsPayload as { sensors?: SensorRow[] }).sensors ?? [];
        const ltcResults = ltcPayload ? toLtcResultSummaries(ltcPayload) : get().ltcResults;
        set((state) => ({
          config: nextConfig,
          serverRunconfig: runconfig,
          sensors,
          ltcResults,
          assets: upsertAssets(state.assets, [buildConfigAsset(nextConfig)]),
        }));
      }
      const graph = createWorkflowGraph(nextConfig, get().capabilities, graphContextFromState(get()));
      set((state) => ({
        workflowNodes: graph.nodes,
        workflowEdges: graph.edges,
        busyLabel: null,
        activity: appendActivity(state.activity, "Rebuilt canvas from config", "ok", `${graph.nodes.length} nodes`),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Canvas rebuild failed", "error", asErrorMessage(error)),
      }));
    }
  },

  executeWorkflowGraph: async (mode) => {
    const session = get().session;
    if (!session) return;
    const payload = toExecutionRequest(get().workflowNodes, get().workflowEdges, mode);
    set({
      busyLabel: mode === "auto" ? "Executing workflow" : "Executing step",
      activeTab: "workflow",
      workflowStatus: {
        run_id: null,
        is_running: true,
        cancelled: false,
        node_statuses: Object.fromEntries(payload.nodes.map((node) => [node.id, "pending"])),
        events: [],
      },
    });
    try {
      if (mode === "auto") {
        await streamWorkflowExecution(get().apiBaseUrl, session.session_id, payload, (event) => {
          set((state) => {
            const current = state.workflowStatus;
            const nodeStatuses = { ...(current?.node_statuses ?? {}) };
            if (event.node_id && event.status) nodeStatuses[event.node_id] = event.status;
            const events = [...(current?.events ?? []), event].slice(-400);
            const isFinished = event.event_type === "run_finished" || event.event_type === "run_cancelled";
            return {
              workflowStatus: {
                run_id: event.run_id || current?.run_id || null,
                is_running: !isFinished,
                cancelled: event.event_type === "run_cancelled",
                node_statuses: nodeStatuses,
                events,
              },
            };
          });
        });
        const streamed = get().workflowStatus;
        set((state) => ({
          busyLabel: null,
          assets: upsertAssets(state.assets, [buildOperationResultAsset("workflow-auto", streamed ?? {})]),
          activity: appendActivity(state.activity, "Workflow auto", "ok", streamed?.cancelled ? "cancelled" : "completed"),
        }));
      } else {
        const response = await apiExecuteWorkflowStep(get().apiBaseUrl, session.session_id, payload);
        set((state) => ({
          workflowStatus: {
            run_id: response.run_id,
            is_running: false,
            cancelled: false,
            node_statuses: response.node_statuses,
            events: response.events,
          },
          assets: upsertAssets(state.assets, [buildOperationResultAsset("workflow-manual", response)]),
          busyLabel: null,
          activity: appendActivity(state.activity, "Workflow manual", "ok", response.status),
        }));
      }
      // Pull freshly computed results (LTC, ensemble) so read-only surfaces
      // like the Results tab reflect the run without needing a manual stage run.
      await Promise.all([get().refreshWorkspace(), get().refreshResults()]);
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        workflowStatus: state.workflowStatus
          ? { ...state.workflowStatus, is_running: false }
          : state.workflowStatus,
        activity: appendActivity(state.activity, `Workflow ${mode} failed`, "error", asErrorMessage(error)),
      }));
    }
  },

  stopWorkflowGraph: async () => {
    const session = get().session;
    if (!session) return;
    try {
      await apiStopWorkflow(get().apiBaseUrl, session.session_id);
      set((state) => ({
        activity: appendActivity(state.activity, "Workflow stop requested", "ok", ""),
      }));
    } catch (error) {
      set((state) => ({
        activity: appendActivity(state.activity, "Workflow stop failed", "error", asErrorMessage(error)),
      }));
    }
  },

  refreshWorkflowStatus: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const status = await apiGetWorkflowStatus(get().apiBaseUrl, session.session_id);
      set({ workflowStatus: status });
    } catch {
      /* non-fatal */
    }
  },

  refreshWorkflowSnapshots: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const payload = await apiListSnapshots(get().apiBaseUrl, session.session_id);
      set({ workflowSnapshots: payload.snapshots });
    } catch {
      /* non-fatal */
    }
  },

  replaceWorkflowRunConfig: async (runconfig) => {
    const session = get().session;
    if (!session) return false;
    set({ busyLabel: "Saving run config" });
    try {
      const response = await apiReplaceWorkflowRunConfig(get().apiBaseUrl, session.session_id, runconfig);
      const nextConfig = hydrateConfigFromRunconfig(response.runconfig);
      set((state) => ({
        config: nextConfig,
        serverRunconfig: response.runconfig,
        assets: upsertAssets(state.assets, [buildConfigAsset(nextConfig)]),
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved run config", "ok", response.file_path),
      }));
      return true;
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Save run config failed", "error", asErrorMessage(error)),
      }));
      return false;
    }
  },

  refreshWorkflowRuns: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const payload = await apiListWorkflowRuns(get().apiBaseUrl, session.session_id);
      set((state) => ({
        workflowRuns: payload.runs,
        selectedWorkflowRunIds: state.selectedWorkflowRunIds.filter((runId) => payload.runs.some((run) => run.run_id === runId)),
      }));
    } catch {
      /* non-fatal; run history is optional until a canvas run completes */
    }
  },

  setSelectedWorkflowRunIds: (runIds) => set({
    selectedWorkflowRunIds: [...new Set(runIds)].slice(0, 4),
    workflowRunComparison: null,
  }),

  compareWorkflowRuns: async () => {
    const session = get().session;
    const runIds = get().selectedWorkflowRunIds;
    if (!session || runIds.length < 2) return;
    set({ busyLabel: "Comparing runs" });
    try {
      const response = await apiCompareWorkflowRuns(get().apiBaseUrl, session.session_id, runIds);
      set((state) => ({
        workflowRunComparison: response,
        busyLabel: null,
        activity: appendActivity(state.activity, "Compared workflow runs", "ok", response.run_ids.map((runId) => runId.slice(0, 8)).join(", ")),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Run comparison failed", "error", asErrorMessage(error)),
      }));
    }
  },

  saveWorkflowSnapshot: async (name) => {
    const session = get().session;
    if (!session || !name.trim()) return;
    set({ busyLabel: "Saving snapshot" });
    try {
      await apiSaveSnapshot(get().apiBaseUrl, session.session_id, name.trim(), {
        nodes: get().workflowNodes,
        edges: get().workflowEdges,
      });
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved snapshot", "ok", name.trim()),
      }));
      await get().refreshWorkflowSnapshots();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Snapshot save failed", "error", asErrorMessage(error)),
      }));
    }
  },

  loadWorkflowSnapshot: async (name) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Loading snapshot" });
    try {
      const response = await apiLoadSnapshot(get().apiBaseUrl, session.session_id, name);
      const snapshot = response.snapshot as
        | { nodes?: WorkflowCanvasNode[]; edges?: WorkflowCanvasEdge[] }
        | undefined;
      set((state) => ({
        workflowNodes: snapshot?.nodes ?? state.workflowNodes,
        workflowEdges: snapshot?.edges ?? state.workflowEdges,
        busyLabel: null,
        activity: appendActivity(state.activity, "Loaded snapshot", "ok", name),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Snapshot load failed", "error", asErrorMessage(error)),
      }));
    }
  },

  forkWorkflowBranch: async (name, fromNodeId) => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Forking branch" });
    try {
      const response = await apiForkBranch(get().apiBaseUrl, session.session_id, {
        name,
        from_node_id: fromNodeId,
      });
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Forked branch", "ok", response.branch_session_id),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Branch fork failed", "error", asErrorMessage(error)),
      }));
    }
  },

  // ---- Phase G: copilot / compare -----------------------------------------

  setChatSettings: (settings) => {
    writeChatSettings(settings);
    set({ chatSettings: settings });
  },

  sendChatMessage: async (content) => {
    const session = get().session;
    if (!session || content.trim().length === 0) return;
    const settings = get().chatSettings;
    if (!settings.apiKey) {
      set((state) => ({
        activity: appendActivity(state.activity, "Copilot needs an API key", "error", "Set one in the settings drawer."),
      }));
      return;
    }

    const userMsg: CopilotMessage = {
      id: `cu-${Date.now()}`,
      role: "user",
      content,
      status: "complete",
      toolCalls: [],
    };
    const assistantId = `ca-${Date.now()}`;
    const assistantMsg: CopilotMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      status: "streaming",
      toolCalls: [],
    };
    set((state) => ({
      chatMessages: [...state.chatMessages, userMsg, assistantMsg],
      busyLabel: "Streaming copilot reply",
    }));

    const patchAssistant = (updater: (m: CopilotMessage) => CopilotMessage) => {
      set((state) => ({
        chatMessages: state.chatMessages.map((m) => (m.id === assistantId ? updater(m) : m)),
      }));
    };

    const upsertToolCall = (evt: CopilotToolEvent) => {
      patchAssistant((m) => {
        const idx = m.toolCalls.findIndex((t) => t.id === evt.id);
        if (idx === -1) return { ...m, toolCalls: [...m.toolCalls, evt] };
        const next = [...m.toolCalls];
        next[idx] = { ...next[idx], ...evt };
        return { ...m, toolCalls: next };
      });
    };

    try {
      const history = get()
        .chatMessages.filter((m) => m.id !== assistantId && m.id !== userMsg.id)
        .map((m) => ({ role: m.role, content: m.content }));
      const response = await streamCopilotReply({
        prompt: content,
        settings,
        sessionId: session.session_id,
        apiBaseUrl: get().apiBaseUrl,
        context: {
          summary: get().summary,
          config: get().config,
          sensors: get().sensors,
          scenarios: get().scenarios,
        },
        handlers: {
          onUpdateRunconfigField: async ({ key, value }) => {
            const res = await updateSessionConfig(get().apiBaseUrl, session.session_id, [{ key, value }]);
            await get().refreshWorkspace();
            return res;
          },
          onCallSessionRoute: async ({ label, method, path, body }) => {
            return get().invokeSessionOperation(label, method as HttpMethod, path, body);
          },
        },
        callbacks: {
          onTextDelta: (delta) => patchAssistant((m) => ({ ...m, content: delta })),
          onToolEvent: upsertToolCall,
        },
        history,
      });
      patchAssistant((m) => ({
        ...m,
        content: response.text || m.content,
        status: "complete",
      }));
      set({ busyLabel: null });
    } catch (error) {
      const detail = asErrorMessage(error);
      patchAssistant((m) => ({ ...m, status: "error", content: m.content || detail }));
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Copilot failed", "error", detail),
      }));
    }
  },

  setCompareSlot: (slotIndex, scenarioName) => {
    set((state) => {
      const next = [...state.compareSlotNames];
      next[slotIndex] = scenarioName;
      return { compareSlotNames: next };
    });
  },

  runCompare: async () => {
    const session = get().session;
    if (!session) return;
    set({ busyLabel: "Comparing scenarios" });
    try {
      // Compare requires branch session ids; for an in-session comparison we
      // fork the named scenarios' configs into branches first. For now we pass
      // the active session as the baseline and rely on saved-scenario runconfigs
      // being available server-side via the workflow compare endpoint.
      const response = await compareWorkflowBranches(get().apiBaseUrl, session.session_id, []);
      set((state) => ({
        compareResult: response,
        busyLabel: null,
        activity: appendActivity(state.activity, "Compared", "ok", response.session_ids.join(", ")),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Compare failed", "error", asErrorMessage(error)),
      }));
    }
  },

}));

function deriveApiBaseUrl(): string {
  const env = import.meta.env.VITE_API_BASE_URL;
  if (typeof env === "string" && env.length > 0) return env;
  if (typeof window !== "undefined" && window.location.origin.length > 0) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8000";
}
