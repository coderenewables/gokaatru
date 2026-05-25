import { create } from "zustand";

import {
  callSessionRoute,
  compareWorkflowBranches,
  createSession,
  deleteScenario as apiDeleteScenario,
  downloadBrightHubReanalysis,
  executeWorkflow,
  executeWorkflowStep,
  fetchOpenApiSpec,
  fetchBrightHubReanalysisNodes,
  forkWorkflowBranch,
  getAnalysisSummary,
  getBrightHubStatus,
  getDatasetPreview,
  getDefaultApiBaseUrl,
  getSensors,
  getSessionConfig,
  getSessionSummary,
  getWorkflowCapabilities,
  getWorkflowStatus,
  importBrightHubLocation,
  invokeWindKitRoute,
  listBrightHubLocations,
  listDatasets,
  listScenarios,
  listWorkflowSnapshots,
  loginBrightHub,
  loadDatasetIntoSession,
  loadWorkflowSnapshot,
  logoutBrightHub,
  saveScenario as apiSaveScenario,
  saveWorkflowSnapshot,
  updateSessionConfig,
  uploadSessionFile as apiUploadSessionFile,
  uploadSharedDataset as apiUploadSharedDataset,
  type AnalysisSummary,
  type BrightHubImportLocationPayload,
  type BrightHubLocation,
  type BrightHubReanalysisDownloadResponse,
  type BrightHubReanalysisNodesResponse,
  type BrightHubStatusResponse,
  type DatasetPreview,
  type HttpMethod,
  type ScenarioSnapshot,
  type SessionSummary,
  type SharedDatasetSummary,
  type WorkflowCompareResponse,
  type WorkflowDispatchCapability,
  type WorkflowExecutionResponse,
  type WorkflowExecutionStatusResponse,
  type WorkflowForkBranchResponse,
  type WorkflowSnapshotSummary,
} from "../lib/api";
import { buildRunconfigUpdates, hydrateConfigFromRunconfig, serializeConfigToRunconfig, setConfigValue } from "../lib/configSync";
import { streamCopilotReply, type CopilotToolEvent } from "../lib/copilotAgent";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { buildConfigAsset, buildDatasetPreviewAsset, buildOperationResultAsset, buildSensorInventoryAsset, buildSummaryAsset, buildWindKitResultAsset, type NormalizedAsset, upsertAssets } from "../lib/normalization";
import { extractWindKitTools, type WindKitToolDefinition } from "../lib/openapi";
import { createWorkflowGraph, toExecutionRequest, type WorkflowCanvasEdge, type WorkflowCanvasNode } from "../lib/workflow";
import type { WindAnalysisConfig } from "../types/analysis";

type PhaseTab = "setup" | "workflow" | "windkit" | "copilot" | "compare";
type ScenarioCompareSlot = "baseline" | "run2" | "run3";
const ACTIVE_SESSION_STORAGE_KEY = "gokaatru-active-session-id";

interface ActivityEntry {
  id: string;
  label: string;
  timestamp: string;
  status: "ok" | "error";
  detail: string;
}

interface ChatSettings {
  provider: string;
  model: string;
  apiKey: string;
}

interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "complete" | "error";
  reasoning: string;
  toolCalls: CopilotToolEvent[];
}

type ScenarioCompareSlots = Record<ScenarioCompareSlot, string | null>;

interface WorkspaceStore {
  activeTab: PhaseTab;
  apiBaseUrl: string;
  session: SessionSummary | null;
  sessionStatus: "idle" | "loading" | "ready" | "error";
  sessionError: string | null;
  busyLabel: string | null;
  config: WindAnalysisConfig;
  serverRunconfig: Record<string, unknown>;
  summary: AnalysisSummary | null;
  datasets: SharedDatasetSummary[];
  datasetPreview: DatasetPreview | null;
  sensors: Array<Record<string, unknown>>;
  assets: NormalizedAsset[];
  scenarios: ScenarioSnapshot[];
  scenarioCompareSlots: ScenarioCompareSlots;
  brighthubStatus: BrightHubStatusResponse | null;
  brighthubLocations: BrightHubLocation[];
  brighthubReanalysis: BrightHubReanalysisNodesResponse | null;
  capabilities: WorkflowDispatchCapability[];
  workflowNodes: WorkflowCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
  workflowStatus: WorkflowExecutionStatusResponse | null;
  workflowSnapshots: WorkflowSnapshotSummary[];
  workflowBranches: WorkflowForkBranchResponse[];
  windkitTools: WindKitToolDefinition[];
  windkitResponse: unknown;
  chatSettings: ChatSettings;
  chatMessages: CopilotMessage[];
  compareResult: WorkflowCompareResponse | null;
  lastOperation: unknown;
  activity: ActivityEntry[];
  setActiveTab: (tab: PhaseTab) => void;
  updateConfigValue: (path: string, value: unknown) => void;
  resetConfig: () => void;
  restoreSession: () => Promise<void>;
  bootstrapSession: () => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  saveConfig: () => Promise<void>;
  previewDataset: (datasetId: string) => Promise<void>;
  loadDataset: (datasetId: string) => Promise<void>;
  uploadSharedDataset: (payload: { name?: string; timeseriesFile: File; datamodelFile: File }) => Promise<void>;
  uploadSessionFile: (kind: "timeseries" | "datamodel", file: File) => Promise<void>;
  refreshBrightHub: () => Promise<void>;
  loginBrightHub: (credentials: { clientId: string; clientSecret: string }) => Promise<void>;
  logoutBrightHub: () => Promise<void>;
  importBrightHubLocation: (payload: BrightHubImportLocationPayload) => Promise<void>;
  fetchBrightHubReanalysisNodes: (payload: { latitude: number; longitude: number }) => Promise<void>;
  downloadBrightHubReanalysis: (payload: { dataset: "ERA5" | "MERRA-2"; source?: "brighthub" | "earthdatahub"; useNodes: "era5" | "merra2" }) => Promise<void>;
  saveScenario: (name: string) => Promise<void>;
  deleteScenario: (scenarioIndex: number) => Promise<void>;
  setScenarioCompareSlot: (slot: ScenarioCompareSlot, scenarioName: string | null) => void;
  invokeSessionOperation: <T>(label: string, method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown) => Promise<T>;
  setWorkflowGraph: (nodes: WorkflowCanvasNode[], edges: WorkflowCanvasEdge[]) => void;
  updateWorkflowNode: (nodeId: string, updater: (node: WorkflowCanvasNode) => WorkflowCanvasNode) => void;
  executeWorkflow: (mode: "auto" | "manual") => Promise<void>;
  refreshWorkflowStatus: () => Promise<void>;
  saveSnapshot: (name: string) => Promise<void>;
  loadSnapshot: (name: string) => Promise<void>;
  forkBranch: (name: string, fromNodeId?: string) => Promise<void>;
  compareBranches: (branchSessionIds: string[]) => Promise<void>;
  setChatSettings: (settings: ChatSettings) => void;
  sendChatMessage: (content: string) => Promise<void>;
  invokeWindKitTool: (toolPath: string, payload: unknown) => Promise<void>;
}

function createId(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}-${suffix}`;
}

function safeStorageRead(): ChatSettings {
  if (typeof window === "undefined") {
    return { provider: "openai", model: "gpt-4o", apiKey: "" };
  }
  try {
    const raw = window.localStorage.getItem("gokaatru-chat-settings");
    if (!raw) {
      return { provider: "openai", model: "gpt-4o", apiKey: "" };
    }
    const parsed = JSON.parse(raw) as Partial<ChatSettings>;
    return {
      provider: typeof parsed.provider === "string" ? parsed.provider : "openai",
      model: typeof parsed.model === "string" ? parsed.model : "gpt-4o",
      apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : "",
    };
  } catch {
    return { provider: "openai", model: "gpt-4o", apiKey: "" };
  }
}

function safeStorageWrite(settings: ChatSettings) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem("gokaatru-chat-settings", JSON.stringify(settings));
}

function readStoredSessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const normalized = raw.trim();
    return normalized.length > 0 ? normalized : null;
  } catch {
    return null;
  }
}

function writeStoredSessionId(sessionId: string | null) {
  if (typeof window === "undefined") {
    return;
  }
  if (!sessionId) {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
}

function asErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function appendActivity(activity: ActivityEntry[], label: string, status: ActivityEntry["status"], detail: string): ActivityEntry[] {
  const entry: ActivityEntry = {
    id: createId("activity"),
    label,
    status,
    detail,
    timestamp: new Date().toISOString(),
  };
  return [entry, ...activity].slice(0, 18);
}

function createDefaultScenarioCompareSlots(): ScenarioCompareSlots {
  return {
    baseline: null,
    run2: null,
    run3: null,
  };
}

function normalizeScenarioSlots(current: ScenarioCompareSlots, scenarios: ScenarioSnapshot[]): ScenarioCompareSlots {
  const available = new Set(scenarios.map((scenario) => scenario.name));
  const sanitized: ScenarioCompareSlots = {
    baseline: current.baseline && available.has(current.baseline) ? current.baseline : null,
    run2: current.run2 && available.has(current.run2) ? current.run2 : null,
    run3: current.run3 && available.has(current.run3) ? current.run3 : null,
  };
  const ordered = [...scenarios].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const slotOrder: ScenarioCompareSlot[] = ["baseline", "run2", "run3"];
  const used = new Set(Object.values(sanitized).filter((value): value is string => Boolean(value)));

  for (const slot of slotOrder) {
    if (sanitized[slot] !== null) {
      continue;
    }
    const nextScenario = ordered.find((scenario) => !used.has(scenario.name));
    sanitized[slot] = nextScenario?.name ?? null;
    if (nextScenario) {
      used.add(nextScenario.name);
    }
  }

  return sanitized;
}

function upsertCopilotToolCall(toolCalls: CopilotToolEvent[], nextEvent: CopilotToolEvent): CopilotToolEvent[] {
  const existingIndex = toolCalls.findIndex((toolCall) => toolCall.id === nextEvent.id);
  if (existingIndex === -1) {
    return [...toolCalls, nextEvent];
  }

  return toolCalls.map((toolCall, index) => (index === existingIndex ? { ...toolCall, ...nextEvent } : toolCall));
}

export const useWorkspaceStore = create<WorkspaceStore>((set, get) => ({
  activeTab: "setup",
  apiBaseUrl: getDefaultApiBaseUrl(),
  session: null,
  sessionStatus: "idle",
  sessionError: null,
  busyLabel: null,
  config: createDefaultWindAnalysisConfig(),
  serverRunconfig: {},
  summary: null,
  datasets: [],
  datasetPreview: null,
  sensors: [],
  assets: [buildConfigAsset(createDefaultWindAnalysisConfig())],
  scenarios: [],
  scenarioCompareSlots: createDefaultScenarioCompareSlots(),
  brighthubStatus: null,
  brighthubLocations: [],
  brighthubReanalysis: null,
  capabilities: [],
  workflowNodes: [],
  workflowEdges: [],
  workflowStatus: null,
  workflowSnapshots: [],
  workflowBranches: [],
  windkitTools: [],
  windkitResponse: null,
  chatSettings: safeStorageRead(),
  chatMessages: [],
  compareResult: null,
  lastOperation: null,
  activity: [],

  setActiveTab: (tab) => set({ activeTab: tab }),

  updateConfigValue: (path, value) => {
    const nextConfig = setConfigValue(get().config, path, value);
    const graph = createWorkflowGraph(nextConfig, get().capabilities);
    const nextAssets = upsertAssets(get().assets, [buildConfigAsset(nextConfig)]);
    set({ config: nextConfig, workflowNodes: graph.nodes, workflowEdges: graph.edges, assets: nextAssets });
  },

  resetConfig: () => {
    const nextConfig = createDefaultWindAnalysisConfig();
    const graph = createWorkflowGraph(nextConfig, get().capabilities);
    set({ config: nextConfig, workflowNodes: graph.nodes, workflowEdges: graph.edges, assets: [buildConfigAsset(nextConfig)] });
  },

  restoreSession: async () => {
    if (get().session !== null || get().sessionStatus === "loading") {
      return;
    }

    const storedSessionId = readStoredSessionId();
    if (!storedSessionId) {
      return;
    }

    set({ sessionStatus: "loading", sessionError: null, busyLabel: "Restoring workspace" });
    try {
      const session = await getSessionSummary(get().apiBaseUrl, storedSessionId);
      writeStoredSessionId(session.session_id);
      set({ session, sessionStatus: "ready", busyLabel: null });
      await get().refreshWorkspace();
      set((state) => ({ activity: appendActivity(state.activity, "Restored workspace session", "ok", session.session_id) }));
    } catch (error) {
      writeStoredSessionId(null);
      set((state) => ({
        session: null,
        sessionStatus: "idle",
        sessionError: null,
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved workspace session unavailable", "error", asErrorMessage(error)),
      }));
    }
  },

  bootstrapSession: async () => {
    if (get().sessionStatus === "loading") {
      return;
    }
    set({ sessionStatus: "loading", sessionError: null, busyLabel: "Creating session" });
    try {
      const created = await createSession(get().apiBaseUrl);
      const session = await getSessionSummary(get().apiBaseUrl, created.session_id);
      writeStoredSessionId(session.session_id);
      set({ session, sessionStatus: "ready", busyLabel: null });
      await get().refreshWorkspace();
      set((state) => ({ activity: appendActivity(state.activity, "Created workspace session", "ok", session.session_id) }));
    } catch (error) {
      set((state) => ({
        sessionStatus: "error",
        sessionError: asErrorMessage(error),
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to create workspace session", "error", asErrorMessage(error)),
      }));
    }
  },

  refreshWorkspace: async () => {
    const session = get().session;
    if (!session) {
      return;
    }

    set({ busyLabel: "Refreshing workspace" });
    try {
      const [summary, runconfig, datasetsPayload, sensorsPayload, capabilitiesPayload, workflowStatus, snapshotsPayload, openApiSpec, scenariosPayload, brighthubStatus] =
        await Promise.all([
          getAnalysisSummary(get().apiBaseUrl, session.session_id),
          getSessionConfig(get().apiBaseUrl, session.session_id),
          listDatasets(get().apiBaseUrl),
          getSensors(get().apiBaseUrl, session.session_id).catch(() => ({ sensors: [] })),
          getWorkflowCapabilities(get().apiBaseUrl, session.session_id),
          getWorkflowStatus(get().apiBaseUrl, session.session_id),
          listWorkflowSnapshots(get().apiBaseUrl, session.session_id),
          fetchOpenApiSpec(get().apiBaseUrl).catch(() => ({ paths: {}, components: { schemas: {} } })),
          listScenarios(get().apiBaseUrl, session.session_id).catch(() => ({ scenarios: [] })),
          getBrightHubStatus(get().apiBaseUrl, session.session_id).catch(() => ({ authenticated: false, has_token: false })),
        ]);

      const nextConfig = hydrateConfigFromRunconfig(runconfig);
      const graph = createWorkflowGraph(nextConfig, capabilitiesPayload.capabilities);
      const windkitTools = extractWindKitTools(openApiSpec as never);
      const scenarios = scenariosPayload.scenarios ?? [];
      const brighthubLocations = brighthubStatus.authenticated
        ? (await listBrightHubLocations(get().apiBaseUrl, session.session_id).catch(() => ({ locations: [] }))).locations
        : [];
      const nextAssets = upsertAssets(get().assets, [
        buildConfigAsset(nextConfig),
        buildSummaryAsset(summary),
        buildSensorInventoryAsset(sensorsPayload.sensors ?? []),
      ]);

      set({
        config: nextConfig,
        serverRunconfig: runconfig,
        summary,
        datasets: datasetsPayload.datasets,
        sensors: sensorsPayload.sensors ?? [],
        scenarios,
        scenarioCompareSlots: normalizeScenarioSlots(get().scenarioCompareSlots, scenarios),
        brighthubStatus,
        brighthubLocations,
        capabilities: capabilitiesPayload.capabilities,
        workflowNodes: graph.nodes,
        workflowEdges: graph.edges,
        workflowStatus,
        workflowSnapshots: snapshotsPayload.snapshots,
        windkitTools,
        assets: nextAssets,
        busyLabel: null,
      });
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Workspace refresh failed", "error", asErrorMessage(error)),
      }));
    }
  },

  saveConfig: async () => {
    const session = get().session;
    if (!session) {
      return;
    }
    const nextRunconfig = serializeConfigToRunconfig(get().config);
    const updates = buildRunconfigUpdates(get().serverRunconfig, nextRunconfig);
    if (updates.length === 0) {
      return;
    }

    set({ busyLabel: "Saving config" });
    try {
      const response = await updateSessionConfig(get().apiBaseUrl, session.session_id, updates);
      const nextConfig = hydrateConfigFromRunconfig(response.runconfig);
      const graph = createWorkflowGraph(nextConfig, get().capabilities);
      set((state) => ({
        config: nextConfig,
        serverRunconfig: response.runconfig,
        workflowNodes: graph.nodes,
        workflowEdges: graph.edges,
        assets: upsertAssets(state.assets, [buildConfigAsset(nextConfig)]),
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved central config", "ok", `${updates.length} runconfig update(s)`),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to save config", "error", asErrorMessage(error)),
      }));
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
    if (!session) {
      return;
    }
    set({ busyLabel: "Loading dataset into session" });
    try {
      await loadDatasetIntoSession(get().apiBaseUrl, session.session_id, datasetId);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Loaded shared dataset", "ok", datasetId),
      }));
      await get().previewDataset(datasetId);
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to load shared dataset", "error", asErrorMessage(error)),
      }));
    }
  },

  uploadSharedDataset: async (payload) => {
    set({ busyLabel: "Uploading shared dataset" });
    try {
      const response = await apiUploadSharedDataset(get().apiBaseUrl, payload);
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(
          state.activity,
          "Uploaded shared dataset",
          "ok",
          String(response.dataset_id ?? response.id ?? payload.name ?? payload.timeseriesFile.name),
        ),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Shared dataset upload failed", "error", asErrorMessage(error)),
      }));
    }
  },

  uploadSessionFile: async (kind, file) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: `Uploading ${kind}` });
    try {
      const response = await apiUploadSessionFile(get().apiBaseUrl, session.session_id, kind, file);
      set((state) => ({
        busyLabel: null,
        lastOperation: response,
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

  refreshBrightHub: async () => {
    const session = get().session;
    if (!session) {
      return;
    }

    try {
      const status = await getBrightHubStatus(get().apiBaseUrl, session.session_id);
      const locations = status.authenticated
        ? (await listBrightHubLocations(get().apiBaseUrl, session.session_id).catch(() => ({ locations: [] }))).locations
        : [];
      set({ brighthubStatus: status, brighthubLocations: locations });
    } catch (error) {
      set((state) => ({
        brighthubStatus: { authenticated: false, has_token: false },
        brighthubLocations: [],
        activity: appendActivity(state.activity, "BrightHub refresh failed", "error", asErrorMessage(error)),
      }));
    }
  },

  loginBrightHub: async ({ clientId, clientSecret }) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Connecting to BrightHub" });
    try {
      await loginBrightHub(get().apiBaseUrl, session.session_id, {
        client_id: clientId,
        client_secret: clientSecret,
      });
      set((state) => ({
        busyLabel: null,
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
    if (!session) {
      return;
    }
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
    if (!session) {
      return;
    }
    set({ busyLabel: "Importing BrightHub location" });
    try {
      const response = await importBrightHubLocation(get().apiBaseUrl, session.session_id, payload);
      set((state) => ({
        busyLabel: null,
        lastOperation: response,
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

  fetchBrightHubReanalysisNodes: async (payload) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Finding BrightHub reanalysis nodes" });
    try {
      const response = await fetchBrightHubReanalysisNodes(get().apiBaseUrl, session.session_id, payload);
      set((state) => ({
        brighthubReanalysis: response,
        busyLabel: null,
        lastOperation: response,
        assets: upsertAssets(state.assets, [buildOperationResultAsset("brighthub-reanalysis-nodes", response)]),
        activity: appendActivity(state.activity, "Fetched BrightHub nodes", "ok", `${response.era5_nodes.length} ERA5 / ${response.merra2_nodes.length} MERRA-2`),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "BrightHub node lookup failed", "error", asErrorMessage(error)),
      }));
    }
  },

  downloadBrightHubReanalysis: async ({ dataset, source, useNodes }) => {
    const session = get().session;
    const nodesPayload = get().brighthubReanalysis;
    if (!session || !nodesPayload) {
      return;
    }

    const nodes = useNodes === "merra2" ? nodesPayload.merra2_nodes : nodesPayload.era5_nodes;
    if (nodes.length === 0) {
      return;
    }

    set({ busyLabel: `Downloading ${dataset} reanalysis` });
    try {
      const response: BrightHubReanalysisDownloadResponse = await downloadBrightHubReanalysis(
        get().apiBaseUrl,
        session.session_id,
        { dataset, source, nodes },
      );
      set((state) => ({
        busyLabel: null,
        lastOperation: response,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(`brighthub-${dataset.toLowerCase()}-download`, response)]),
        activity: appendActivity(state.activity, `Downloaded ${dataset} reanalysis`, "ok", `${response.items.length} node(s)`),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, `${dataset} download failed`, "error", asErrorMessage(error)),
      }));
    }
  },

  saveScenario: async (name) => {
    const session = get().session;
    if (!session || name.trim().length === 0) {
      return;
    }
    set({ busyLabel: "Saving scenario" });
    try {
      const response = await apiSaveScenario(get().apiBaseUrl, session.session_id, name.trim());
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved scenario", "ok", response.name),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Scenario save failed", "error", asErrorMessage(error)),
      }));
    }
  },

  deleteScenario: async (scenarioIndex) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Deleting scenario" });
    try {
      const response = await apiDeleteScenario(get().apiBaseUrl, session.session_id, scenarioIndex);
      set((state) => ({
        busyLabel: null,
        scenarioCompareSlots: Object.fromEntries(
          Object.entries(state.scenarioCompareSlots).map(([slot, value]) => [slot, value === response.name ? null : value]),
        ) as ScenarioCompareSlots,
        activity: appendActivity(state.activity, "Deleted scenario", "ok", response.name),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Scenario delete failed", "error", asErrorMessage(error)),
      }));
    }
  },

  setScenarioCompareSlot: (slot, scenarioName) => {
    set((state) => ({
      scenarioCompareSlots: {
        ...state.scenarioCompareSlots,
        [slot]: scenarioName,
      },
    }));
  },

  invokeSessionOperation: async <T,>(label: string, method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown) => {
    const session = get().session;
    if (!session) {
      throw new Error("Session is not initialized");
    }
    set({ busyLabel: label });
    try {
      const response = await callSessionRoute<T>(get().apiBaseUrl, session.session_id, method, path, body);
      set((state) => ({
        busyLabel: null,
        lastOperation: response,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(label, response)]),
        activity: appendActivity(state.activity, label, "ok", "Operation completed"),
      }));
      await get().refreshWorkspace();
      return response;
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, label, "error", asErrorMessage(error)),
      }));
      throw error;
    }
  },

  setWorkflowGraph: (nodes, edges) => set({ workflowNodes: nodes, workflowEdges: edges }),

  updateWorkflowNode: (nodeId, updater) => {
    set((state) => ({
      workflowNodes: state.workflowNodes.map((node) => (node.id === nodeId ? updater(node) : node)),
    }));
  },

  executeWorkflow: async (mode) => {
    const session = get().session;
    if (!session) {
      return;
    }
    const payload = toExecutionRequest(get().workflowNodes, get().workflowEdges, mode);
    set({ busyLabel: mode === "auto" ? "Executing workflow" : "Executing workflow step" });
    try {
      const response: WorkflowExecutionResponse =
        mode === "auto"
          ? await executeWorkflow(get().apiBaseUrl, session.session_id, payload)
          : await executeWorkflowStep(get().apiBaseUrl, session.session_id, payload);

      set((state) => ({
        workflowStatus: {
          run_id: response.run_id,
          is_running: false,
          cancelled: false,
          node_statuses: response.node_statuses,
          events: response.events,
        },
        lastOperation: response,
        assets: upsertAssets(state.assets, [buildOperationResultAsset(`workflow-${mode}`, response)]),
        busyLabel: null,
        activity: appendActivity(state.activity, `Workflow ${mode}`, "ok", response.status),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, `Workflow ${mode} failed`, "error", asErrorMessage(error)),
      }));
    }
  },

  refreshWorkflowStatus: async () => {
    const session = get().session;
    if (!session) {
      return;
    }
    const workflowStatus = await getWorkflowStatus(get().apiBaseUrl, session.session_id);
    set({ workflowStatus });
  },

  saveSnapshot: async (name) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Saving workflow snapshot" });
    try {
      await saveWorkflowSnapshot(get().apiBaseUrl, session.session_id, name, {
        nodes: get().workflowNodes,
        edges: get().workflowEdges,
      });
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Saved workflow snapshot", "ok", name),
      }));
      await get().refreshWorkspace();
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to save workflow snapshot", "error", asErrorMessage(error)),
      }));
    }
  },

  loadSnapshot: async (name) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Loading workflow snapshot" });
    try {
      const response = await loadWorkflowSnapshot(get().apiBaseUrl, session.session_id, name);
      const snapshot = response.snapshot as { nodes?: WorkflowCanvasNode[]; edges?: WorkflowCanvasEdge[] };
      set((state) => ({
        workflowNodes: snapshot.nodes ?? state.workflowNodes,
        workflowEdges: snapshot.edges ?? state.workflowEdges,
        busyLabel: null,
        activity: appendActivity(state.activity, "Loaded workflow snapshot", "ok", name),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to load workflow snapshot", "error", asErrorMessage(error)),
      }));
    }
  },

  forkBranch: async (name, fromNodeId) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Forking workflow branch" });
    try {
      const response = await forkWorkflowBranch(get().apiBaseUrl, session.session_id, { name, from_node_id: fromNodeId });
      set((state) => ({
        workflowBranches: [response, ...state.workflowBranches],
        busyLabel: null,
        activity: appendActivity(state.activity, "Forked workflow branch", "ok", response.branch_session_id),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Failed to fork workflow branch", "error", asErrorMessage(error)),
      }));
    }
  },

  compareBranches: async (branchSessionIds) => {
    const session = get().session;
    if (!session) {
      return;
    }
    set({ busyLabel: "Comparing branches" });
    try {
      const response = await compareWorkflowBranches(get().apiBaseUrl, session.session_id, branchSessionIds);
      set((state) => ({
        compareResult: response,
        busyLabel: null,
        activity: appendActivity(state.activity, "Compared workflow branches", "ok", response.session_ids.join(", ")),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Branch comparison failed", "error", asErrorMessage(error)),
      }));
    }
  },

  setChatSettings: (settings) => {
    safeStorageWrite(settings);
    set({ chatSettings: settings });
  },

  sendChatMessage: async (content) => {
    const session = get().session;
    if (!session || content.trim().length === 0) {
      return;
    }

    const userMessage: CopilotMessage = {
      id: createId("chat-user"),
      role: "user",
      content,
      status: "complete",
      reasoning: "",
      toolCalls: [],
    };
    const assistantId = createId("chat-assistant");
    const assistantMessage: CopilotMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      status: "streaming",
      reasoning: "",
      toolCalls: [],
    };

    const patchAssistant = (updater: (message: CopilotMessage) => CopilotMessage) => {
      set((state) => ({
        chatMessages: state.chatMessages.map((message) => (message.id === assistantId ? updater(message) : message)),
      }));
    };

    set((state) => ({
      chatMessages: [...state.chatMessages, userMessage, assistantMessage],
      busyLabel: "Streaming copilot reply",
    }));

    try {
      const response = await streamCopilotReply({
        prompt: content,
        settings: get().chatSettings,
        context: {
          summary: get().summary,
          config: get().config,
          sensors: get().sensors,
          assets: get().assets,
          scenarios: get().scenarios,
          windkitTools: get().windkitTools,
        },
        handlers: {
          getWorkspaceContext: async () => ({
            summary: get().summary,
            config: get().config,
            sensors: get().sensors,
            assets: get().assets,
            scenarios: get().scenarios,
            windkitTools: get().windkitTools.map((tool) => ({ path: tool.path, category: tool.category, summary: tool.summary })),
          }),
          updateRunconfigField: async ({ key, value }) => {
            const updateResponse = await updateSessionConfig(get().apiBaseUrl, session.session_id, [{ key, value }]);
            const nextConfig = hydrateConfigFromRunconfig(updateResponse.runconfig);
            const graph = createWorkflowGraph(nextConfig, get().capabilities);
            set((state) => ({
              config: nextConfig,
              serverRunconfig: updateResponse.runconfig,
              workflowNodes: graph.nodes,
              workflowEdges: graph.edges,
              assets: upsertAssets(state.assets, [buildConfigAsset(nextConfig)]),
            }));
            await get().refreshWorkspace();
            return updateResponse;
          },
          callSessionRoute: async ({ label, method, path, body }) => {
            const routeResponse = await callSessionRoute(
              get().apiBaseUrl,
              session.session_id,
              method as HttpMethod,
              path,
              body,
            );
            set((state) => ({
              lastOperation: routeResponse,
              assets: upsertAssets(state.assets, [buildOperationResultAsset(label, routeResponse)]),
            }));
            await get().refreshWorkspace();
            return routeResponse;
          },
          callWindKitRoute: async ({ routePath, payload }) => {
            const windkitResponse = await invokeWindKitRoute(get().apiBaseUrl, routePath, payload);
            set((state) => ({
              windkitResponse,
              lastOperation: windkitResponse,
              assets: upsertAssets(state.assets, [buildWindKitResultAsset(routePath, windkitResponse.result)]),
            }));
            return windkitResponse;
          },
          listScenarios: async () => {
            const scenariosResponse = await listScenarios(get().apiBaseUrl, session.session_id);
            set((state) => ({
              scenarios: scenariosResponse.scenarios,
              scenarioCompareSlots: normalizeScenarioSlots(state.scenarioCompareSlots, scenariosResponse.scenarios),
            }));
            return scenariosResponse;
          },
        },
        callbacks: {
          onTextDelta: (delta) => {
            patchAssistant((message) => ({
              ...message,
              content: message.content + delta,
            }));
          },
          onReasoningDelta: (delta) => {
            patchAssistant((message) => ({
              ...message,
              reasoning: message.reasoning + delta,
            }));
          },
          onToolEvent: (event) => {
            patchAssistant((message) => ({
              ...message,
              toolCalls: upsertCopilotToolCall(message.toolCalls, event),
            }));
          },
        },
      });

      patchAssistant((message) => ({
        ...message,
        content: response.text || message.content,
        reasoning: response.reasoning || message.reasoning,
        status: "complete",
      }));
      set({ busyLabel: null });
    } catch (error) {
      const detail = asErrorMessage(error);
      patchAssistant((message) => ({
        ...message,
        status: "error",
        content: message.content || detail,
      }));
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "Copilot request failed", "error", detail),
      }));
    }
  },

  invokeWindKitTool: async (toolPath, payload) => {
    set({ busyLabel: "Running WindKit tool" });
    try {
      const response = await invokeWindKitRoute(get().apiBaseUrl, toolPath, payload);
      set((state) => ({
        windkitResponse: response,
        lastOperation: response,
        assets: upsertAssets(state.assets, [buildWindKitResultAsset(toolPath, response.result)]),
        busyLabel: null,
        activity: appendActivity(state.activity, "Ran WindKit tool", "ok", toolPath),
      }));
    } catch (error) {
      set((state) => ({
        busyLabel: null,
        activity: appendActivity(state.activity, "WindKit tool failed", "error", asErrorMessage(error)),
      }));
    }
  },
}));