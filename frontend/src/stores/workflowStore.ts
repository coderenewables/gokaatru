import { MarkerType, type Connection, type Edge, addEdge, type Node } from "@xyflow/react";
import { create } from "zustand";

import type {
  DatasetEntryResponse,
  JsonValue,
  WorkflowExecuteRequest,
  WorkflowExecutionEvent,
  WorkflowExecutionMode,
  WorkflowExecutionResponse,
} from "../lib/types";
import {
  buildTemplateConfig,
  nodeTemplateIndex,
  type NodeConfigValue,
  type NodeStatus,
  type WorkflowNodeData,
} from "../lib/nodeRegistry";
import { foundationLaneGroups, inferLaneIdForTemplate } from "../lib/workflowCanvasModel";
import { workflowTemplateIndex } from "../lib/workflowTemplates";

export type WorkflowNode = Node<WorkflowNodeData>;

export type WorkflowEdge = Edge<{
  dataKeys: string[];
  status: "idle" | "active" | "done";
}>;

type BranchForkPoint = {
  parentBranchId: string;
  nodeId: string;
} | null;

type Branch = {
  id: string;
  name: string;
  color: string;
  sessionId: string | null;
  forkPoint: BranchForkPoint;
};

type BranchState = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  viewport: { x: number; y: number; zoom: number };
};

type BranchSnapshot = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
};

type DatasetEntry = {
  id: DatasetEntryResponse["id"];
  name: DatasetEntryResponse["name"];
  timeseries_file: DatasetEntryResponse["timeseries_file"];
  datamodel_file: DatasetEntryResponse["datamodel_file"];
  uploaded_at: DatasetEntryResponse["uploaded_at"];
  sensor_count: DatasetEntryResponse["sensor_count"];
  date_range: DatasetEntryResponse["date_range"];
  coverage_summary: DatasetEntryResponse["coverage_summary"];
  coverage_pct: DatasetEntryResponse["coverage_pct"];
};

export type WorkflowSnapshot = {
  version: number;
  branches: Branch[];
  branchStates: Record<string, BranchState>;
  datasets: DatasetEntry[];
  activeBranchId?: string;
};

type WorkflowStore = {
  branches: Branch[];
  branchStates: Record<string, BranchState>;
  historyPast: Record<string, BranchSnapshot[]>;
  historyFuture: Record<string, BranchSnapshot[]>;
  datasets: DatasetEntry[];
  executionMode: WorkflowExecutionMode;
  isExecuting: boolean;
  activeRunId: string | null;
  executionEvents: WorkflowExecutionEvent[];
  executionError: string | null;
  setMainBranchSession: (sessionId: string | null) => void;
  setBranchSession: (branchId: string, sessionId: string | null) => void;
  resetWorkflow: () => void;
  clearBranchCanvas: (branchId: string) => void;
  deleteBranch: (branchId: string) => Branch | null;
  forkBranch: (sourceBranchId: string, options: { name?: string; forkNodeId?: string | null; sessionId?: string | null }) => Branch | null;
  getBranchSessionId: (branchId: string) => string | null;
  getForkCandidateNodeId: (branchId: string, selectedNodeId?: string | null) => string | null;
  setDatasets: (datasets: DatasetEntry[]) => void;
  upsertDataset: (dataset: DatasetEntry) => void;
  removeDataset: (datasetId: string) => void;
  setNodes: (branchId: string, nodes: WorkflowNode[]) => void;
  setEdges: (branchId: string, edges: WorkflowEdge[]) => void;
  removeNode: (branchId: string, nodeId: string) => void;
  undo: (branchId: string) => void;
  redo: (branchId: string) => void;
  retryFailedNodes: (branchId: string) => boolean;
  applyWorkflowTemplate: (branchId: string, templateId: string, datasetId?: string | null, defaultBrightHubUuid?: string | null) => string | null;
  serializeSnapshot: () => WorkflowSnapshot;
  hydrateSnapshot: (snapshot: WorkflowSnapshot | null) => void;
  addOperationNode: (branchId: string, templateId: string, position?: { x: number; y: number }, defaultBrightHubUuid?: string | null) => string | null;
  addDatasetNode: (branchId: string, datasetId: string, position?: { x: number; y: number }) => string | null;
  connectNodes: (branchId: string, connection: Connection) => void;
  updateNodeConfig: (branchId: string, nodeId: string, key: string, value: NodeConfigValue) => void;
  setExecutionMode: (mode: WorkflowExecutionMode) => void;
  prepareExecution: (branchId: string, mode: WorkflowExecutionMode, resetStatuses?: boolean) => void;
  applyExecutionEvent: (branchId: string, event: WorkflowExecutionEvent) => void;
  applyExecutionResult: (branchId: string, result: WorkflowExecutionResponse) => void;
  setExecutionError: (message: string | null) => void;
  stopExecution: () => void;
  clearExecutionEvents: () => void;
  buildExecutionRequest: (branchId: string, mode?: WorkflowExecutionMode) => WorkflowExecuteRequest;
};

const MAX_BRANCHES = 4;
const HISTORY_LIMIT = 50;
const WORKFLOW_SNAPSHOT_VERSION = 1;
const BRANCH_COLORS = ["#0b7a6f", "#1f6fa4", "#b55e2e", "#2d8a5e"];

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function createBranchSnapshot(state: BranchState): BranchSnapshot {
  return {
    nodes: cloneJson(state.nodes),
    edges: cloneJson(state.edges),
  };
}

function stripLegacyGroupNodes(snapshot: BranchSnapshot): BranchSnapshot {
  const removedIds = new Set(
    snapshot.nodes
      .filter((node) => node.type === "groupNode" || node.data.kind === "group")
      .map((node) => node.id),
  );

  if (removedIds.size === 0) {
    return snapshot;
  }

  return {
    nodes: snapshot.nodes.filter((node) => !removedIds.has(node.id)),
    edges: snapshot.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)),
  };
}

function applyBranchSnapshot(state: BranchState, snapshot: BranchSnapshot): BranchState {
  return {
    ...state,
    nodes: cloneJson(snapshot.nodes),
    edges: cloneJson(snapshot.edges),
  };
}

function pushSnapshot(history: BranchSnapshot[], snapshot: BranchSnapshot): BranchSnapshot[] {
  const next = [...history, snapshot];
  return next.slice(Math.max(0, next.length - HISTORY_LIMIT));
}

function createDataFlowEdge(source: string, target: string, branchColor: string, id?: string): WorkflowEdge {
  return {
    id: id ?? `${source}->${target}`,
    source,
    target,
    type: "dataFlowEdge",
    markerEnd: { type: MarkerType.ArrowClosed, color: branchColor },
    animated: false,
    style: {
      stroke: branchColor,
    },
    data: {
      dataKeys: [],
      status: "idle",
    },
  };
}

function createHistoryIndex(branches: Branch[]): Record<string, BranchSnapshot[]> {
  return Object.fromEntries(branches.map((branch) => [branch.id, []]));
}

function asNodeStatus(status: string | null | undefined): NodeStatus | null {
  if (status === "idle" || status === "pending" || status === "running" || status === "done" || status === "error" || status === "skipped") {
    return status;
  }
  return null;
}

function toJsonRecord(config: Record<string, NodeConfigValue> | undefined): Record<string, JsonValue> {
  if (!config) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [key, value as JsonValue]),
  );
}

function nextBranchColor(index: number): string {
  return BRANCH_COLORS[index % BRANCH_COLORS.length];
}

function applyBranchColorToNode(node: WorkflowNode, branchColor: string): WorkflowNode {
  return {
    ...node,
    data: {
      ...node.data,
      branchColor,
    },
  };
}

function recolorEdges(edges: WorkflowEdge[], branchColor: string): WorkflowEdge[] {
  return edges.map((edge) => ({
    ...edge,
    style: {
      ...edge.style,
      stroke: branchColor,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: branchColor,
    },
  }));
}

function collectDescendants(startNodeId: string, edges: WorkflowEdge[]): Set<string> {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const current = adjacency.get(edge.source) ?? [];
    current.push(edge.target);
    adjacency.set(edge.source, current);
  }

  const descendants = new Set<string>();
  const queue: string[] = [startNodeId];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) {
      continue;
    }
    const targets = adjacency.get(current) ?? [];
    for (const target of targets) {
      if (descendants.has(target)) {
        continue;
      }
      descendants.add(target);
      queue.push(target);
    }
  }
  return descendants;
}

function collectAncestors(startNodeId: string, edges: WorkflowEdge[]): Set<string> {
  const reverseAdjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const current = reverseAdjacency.get(edge.target) ?? [];
    current.push(edge.source);
    reverseAdjacency.set(edge.target, current);
  }

  const ancestors = new Set<string>([startNodeId]);
  const queue: string[] = [startNodeId];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) {
      continue;
    }
    const parents = reverseAdjacency.get(current) ?? [];
    for (const parent of parents) {
      if (ancestors.has(parent)) {
        continue;
      }
      ancestors.add(parent);
      queue.push(parent);
    }
  }
  return ancestors;
}

function cloneBranchNodes(
  nodes: WorkflowNode[],
  branchColor: string,
  forkNodeId: string | null,
  edges: WorkflowEdge[],
): WorkflowNode[] {
  const ancestors = forkNodeId ? collectAncestors(forkNodeId, edges) : new Set<string>();
  const descendants = forkNodeId ? collectDescendants(forkNodeId, edges) : new Set<string>();

  return nodes.map((node) => {
    const base = applyBranchColorToNode(node, branchColor);
    if (node.data.kind !== "operation" && node.data.kind !== "dataset") {
      return base;
    }

    if (forkNodeId && ancestors.has(node.id)) {
      return {
        ...base,
        data: {
          ...base.data,
          status: "done",
          stale: false,
        },
      };
    }

    if (forkNodeId && descendants.has(node.id)) {
      return {
        ...base,
        data: {
          ...base.data,
          status: "idle",
          stale: true,
        },
      };
    }

    return {
      ...base,
      data: {
        ...base.data,
        stale: false,
      },
    };
  });
}

function createBaselineNodes(): WorkflowNode[] {
  return [];
}

function createBaselineEdges(): WorkflowEdge[] {
  return [];
}

function resolveDropPosition(existingNodes: WorkflowNode[], position?: { x: number; y: number }) {
  if (position) {
    return position;
  }

  const operationCount = existingNodes.filter((node) => node.data.kind === "operation" || node.data.kind === "dataset").length;
  return {
    x: 120 + (operationCount % 4) * 280,
    y: 360 + Math.floor(operationCount / 4) * 150,
  };
}

function normalizeBrightHubUuid(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function withBrightHubUuidDefaults(
  templateId: string,
  baseConfig: Record<string, NodeConfigValue>,
  defaultBrightHubUuid?: string | null,
): Record<string, NodeConfigValue> {
  if (!templateId.startsWith("brighthub_")) {
    return baseConfig;
  }

  const uuid = normalizeBrightHubUuid(defaultBrightHubUuid);
  if (!uuid) {
    return baseConfig;
  }

  const rawParams = baseConfig.params_json;
  if (typeof rawParams !== "string") {
    return {
      ...baseConfig,
      params_json: JSON.stringify({ uuid }, null, 2),
    };
  }

  try {
    const parsed = JSON.parse(rawParams) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {
        ...baseConfig,
        params_json: JSON.stringify({ uuid }, null, 2),
      };
    }

    const params = parsed as Record<string, unknown>;
    if (typeof params.uuid === "string" && params.uuid.trim() !== "") {
      return baseConfig;
    }

    return {
      ...baseConfig,
      params_json: JSON.stringify({ ...params, uuid }, null, 2),
    };
  } catch {
    return {
      ...baseConfig,
      params_json: JSON.stringify({ uuid }, null, 2),
    };
  }
}

const initialBranchId = "main";
const initialBranchColor = nextBranchColor(0);

function createInitialWorkflowState() {
  return {
    branches: [{ id: initialBranchId, name: "main", color: initialBranchColor, sessionId: null, forkPoint: null }] as Branch[],
    branchStates: {
      [initialBranchId]: {
        nodes: createBaselineNodes(),
        edges: createBaselineEdges(),
        viewport: { x: 0, y: 0, zoom: 0.8 },
      },
    } as Record<string, BranchState>,
    historyPast: { [initialBranchId]: [] } as Record<string, BranchSnapshot[]>,
    historyFuture: { [initialBranchId]: [] } as Record<string, BranchSnapshot[]>,
    datasets: [] as DatasetEntry[],
    executionMode: "auto" as WorkflowExecutionMode,
    isExecuting: false,
    activeRunId: null as string | null,
    executionEvents: [] as WorkflowExecutionEvent[],
    executionError: null as string | null,
  };
}

function summarizeDatasetRange(dataset: DatasetEntry): string {
  const startYear = dataset.date_range.start.slice(0, 4);
  const endYear = dataset.date_range.end.slice(0, 4);
  if (startYear.length === 4 && endYear.length === 4) {
    return `${startYear}-${endYear}`;
  }
  return "Unknown period";
}

export const useWorkflowStore = create<WorkflowStore>((set, get) => ({
  ...createInitialWorkflowState(),
  setMainBranchSession: (sessionId) =>
    set((state) => ({
      branches: state.branches.map((branch) =>
        branch.id === initialBranchId
          ? {
              ...branch,
              sessionId,
            }
          : branch,
      ),
    })),
  setBranchSession: (branchId, sessionId) =>
    set((state) => ({
      branches: state.branches.map((branch) =>
        branch.id === branchId
          ? {
              ...branch,
              sessionId,
            }
          : branch,
      ),
    })),
  resetWorkflow: () => set(createInitialWorkflowState()),
  clearBranchCanvas: (branchId) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return {};
      }

      return {
        isExecuting: false,
        activeRunId: null,
        executionEvents: [],
        executionError: null,
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(state.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: [],
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branchState,
            nodes: createBaselineNodes(),
            edges: createBaselineEdges(),
          },
        },
      };
    }),
  deleteBranch: (branchId) => {
    const state = get();
    if (branchId === initialBranchId) {
      return null;
    }
    const branch = state.branches.find((candidate) => candidate.id === branchId);
    if (!branch) {
      return null;
    }

    set((prev) => {
      if (!prev.branches.some((candidate) => candidate.id === branchId)) {
        return {};
      }

      const nextBranches = prev.branches.filter((candidate) => candidate.id !== branchId);
      const { [branchId]: _removedState, ...nextBranchStates } = prev.branchStates;
      const { [branchId]: _removedPast, ...nextHistoryPast } = prev.historyPast;
      const { [branchId]: _removedFuture, ...nextHistoryFuture } = prev.historyFuture;

      return {
        branches: nextBranches,
        executionEvents: [],
        executionError: null,
        branchStates: nextBranchStates,
        historyPast: nextHistoryPast,
        historyFuture: nextHistoryFuture,
      };
    });

    return branch;
  },
  forkBranch: (sourceBranchId, options) => {
    const state = get();
    if (state.branches.length >= MAX_BRANCHES) {
      return null;
    }

    const sourceBranch = state.branches.find((branch) => branch.id === sourceBranchId);
    const sourceBranchState = state.branchStates[sourceBranchId];
    if (!sourceBranch || !sourceBranchState) {
      return null;
    }

    const branchIndex = state.branches.length;
    let suffix = branchIndex;
    let branchId = `branch-${suffix}`;
    while (state.branches.some((branch) => branch.id === branchId)) {
      suffix += 1;
      branchId = `branch-${suffix}`;
    }

    const branchName = options.name && options.name.trim() ? options.name.trim() : `branch-${suffix}`;
    const branchColor = nextBranchColor(branchIndex);
  const forkNodeId = options.forkNodeId ?? null;

    const forkedBranch: Branch = {
      id: branchId,
      name: branchName,
      color: branchColor,
      sessionId: options.sessionId ?? null,
      forkPoint: forkNodeId
        ? {
            parentBranchId: sourceBranch.id,
            nodeId: forkNodeId,
          }
        : null,
    };

    const clonedNodes = cloneBranchNodes(sourceBranchState.nodes, branchColor, forkNodeId, sourceBranchState.edges);
    const clonedEdges = recolorEdges(sourceBranchState.edges, branchColor).map((edge) => ({
      ...edge,
      animated: false,
      data: {
        dataKeys: edge.data?.dataKeys ?? [],
        status: "idle" as "idle",
      },
    }));

    set((prev) => ({
      branches: [...prev.branches, forkedBranch],
      executionEvents: [],
      executionError: null,
      historyPast: {
        ...prev.historyPast,
        [forkedBranch.id]: [],
      },
      historyFuture: {
        ...prev.historyFuture,
        [forkedBranch.id]: [],
      },
      branchStates: {
        ...prev.branchStates,
        [forkedBranch.id]: {
          nodes: clonedNodes,
          edges: clonedEdges,
          viewport: { ...sourceBranchState.viewport },
        },
      },
    }));

    return forkedBranch;
  },
  getBranchSessionId: (branchId) => {
    const state = get();
    const branch = state.branches.find((candidate) => candidate.id === branchId);
    return branch?.sessionId ?? null;
  },
  getForkCandidateNodeId: (branchId, selectedNodeId = null) => {
    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return null;
    }
    if (selectedNodeId) {
      const selected = branch.nodes.find((node) => node.id === selectedNodeId);
      if (selected && (selected.data.kind === "operation" || selected.data.kind === "dataset") && selected.data.status === "done") {
        return selected.id;
      }
    }

    const fallback = [...branch.nodes]
      .reverse()
      .find((node) => (node.data.kind === "operation" || node.data.kind === "dataset") && node.data.status === "done");
    return fallback?.id ?? null;
  },
  setDatasets: (datasets) => set({ datasets }),
  upsertDataset: (dataset) =>
    set((state) => {
      const existing = state.datasets.find((entry) => entry.id === dataset.id);
      if (existing) {
        return {
          datasets: state.datasets.map((entry) => (entry.id === dataset.id ? dataset : entry)),
        };
      }
      return { datasets: [dataset, ...state.datasets] };
    }),
  removeDataset: (datasetId) =>
    set((state) => ({
      datasets: state.datasets.filter((entry) => entry.id !== datasetId),
    })),
  setNodes: (branchId, nodes) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return {};
      }

      return {
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(state.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: [],
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branchState,
            nodes,
          },
        },
      };
    }),
  setEdges: (branchId, edges) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return {};
      }

      return {
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(state.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: [],
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branchState,
            edges,
          },
        },
      };
    }),
  removeNode: (branchId, nodeId) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return {};
      }

      const selectedNode = branchState.nodes.find((node) => node.id === nodeId);
      if (!selectedNode || selectedNode.data.kind === "group") {
        return {};
      }

      const nextNodes = branchState.nodes.filter((node) => node.id !== nodeId);
      const nextEdges = branchState.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);

      return {
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(state.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: [],
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branchState,
            nodes: nextNodes,
            edges: nextEdges,
          },
        },
      };
    }),
  undo: (branchId) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return {};
      }
      const past = state.historyPast[branchId] ?? [];
      if (past.length === 0) {
        return {};
      }

      const previous = past[past.length - 1];
      const current = createBranchSnapshot(branchState);
      const future = state.historyFuture[branchId] ?? [];

      return {
        historyPast: {
          ...state.historyPast,
          [branchId]: past.slice(0, -1),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: pushSnapshot(future, current),
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: applyBranchSnapshot(branchState, previous),
        },
      };
    }),
  redo: (branchId) =>
    set((state) => {
      const branchState = state.branchStates[branchId];
      const future = state.historyFuture[branchId] ?? [];
      if (!branchState) {
        return {};
      }
      if (future.length === 0) {
        return {};
      }

      const next = future[future.length - 1];
      const current = createBranchSnapshot(branchState);
      const past = state.historyPast[branchId] ?? [];

      return {
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(past, current),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: future.slice(0, -1),
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: applyBranchSnapshot(branchState, next),
        },
      };
    }),
  retryFailedNodes: (branchId) => {
    const state = get();
    const branchState = state.branchStates[branchId];
    if (!branchState) {
      return false;
    }

    const failedNodeIds = branchState.nodes
      .filter((node) => (node.data.kind === "operation" || node.data.kind === "dataset") && node.data.status === "error")
      .map((node) => node.id);

    if (failedNodeIds.length === 0) {
      return false;
    }

    const nodesToReset = new Set<string>(failedNodeIds);
    for (const failedNodeId of failedNodeIds) {
      for (const descendant of collectDescendants(failedNodeId, branchState.edges)) {
        nodesToReset.add(descendant);
      }
    }

    const nextNodes = branchState.nodes.map((node) => {
      if (!nodesToReset.has(node.id) || (node.data.kind !== "operation" && node.data.kind !== "dataset")) {
        return node;
      }
      return {
        ...node,
        data: {
          ...node.data,
          status: "pending" as NodeStatus,
          stale: false,
        },
      };
    });

    const nextEdges = branchState.edges.map((edge) => {
      if (!nodesToReset.has(edge.source) && !nodesToReset.has(edge.target)) {
        return edge;
      }

      return {
        ...edge,
        animated: false,
        data: {
          ...edge.data,
          dataKeys: edge.data?.dataKeys ?? [],
          status: "idle" as "idle",
        },
      };
    });

    set((prev) => ({
      executionEvents: [],
      executionError: null,
      historyPast: {
        ...prev.historyPast,
        [branchId]: pushSnapshot(prev.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
      },
      historyFuture: {
        ...prev.historyFuture,
        [branchId]: [],
      },
      branchStates: {
        ...prev.branchStates,
        [branchId]: {
          ...branchState,
          nodes: nextNodes,
          edges: nextEdges,
        },
      },
    }));

    return true;
  },
  applyWorkflowTemplate: (branchId, templateId, datasetId = null, defaultBrightHubUuid = null) => {
    const state = get();
      const template = workflowTemplateIndex[templateId];
      if (!template) {
        return null;
      }

      const activeBranch = state.branches.find((branch) => branch.id === branchId);
      const branchColor = activeBranch?.color ?? initialBranchColor;
      const branchState = state.branchStates[branchId];
      if (!branchState) {
        return null;
      }
      const laneById = Object.fromEntries(foundationLaneGroups.map((lane) => [lane.id, lane]));
      const laneOffset: Record<string, number> = {};

      const dataset =
        (datasetId ? state.datasets.find((entry) => entry.id === datasetId) : null) ?? state.datasets[0] ?? null;

      const nodes: WorkflowNode[] = [...createBaselineNodes()];
      const edges: WorkflowEdge[] = [...createBaselineEdges()];
      let previousNodeId: string | null = null;
      let firstOperationNodeId: string | null = null;

      if (dataset) {
        const datasetNodeId = `${template.id}-dataset`;
        nodes.push({
          id: datasetNodeId,
          type: "datasetNode",
          position: { x: 120, y: 360 },
          data: {
            kind: "dataset",
            laneId: "group-dataset",
            label: dataset.name,
            description: `${dataset.sensor_count} sensors across ${summarizeDatasetRange(dataset)}`,
            status: "done",
            stale: false,
            branchColor,
            summary: `${dataset.coverage_pct.toFixed(1)}% coverage`,
            badge: "Shared dataset",
          },
        });
        previousNodeId = datasetNodeId;
      }

      for (const [index, step] of template.steps.entries()) {
        const nodeTemplate = nodeTemplateIndex[step.templateId];
        const lane = laneById[step.laneId];
        if (!nodeTemplate || !lane) {
          continue;
        }

        const laneIndex = laneOffset[step.laneId] ?? 0;
        laneOffset[step.laneId] = laneIndex + 1;
        const nodeId = `${template.id}-op-${index + 1}`;
        if (!firstOperationNodeId) {
          firstOperationNodeId = nodeId;
        }
        const config = withBrightHubUuidDefaults(step.templateId, {
          ...buildTemplateConfig(nodeTemplate),
          ...(step.config ?? {}),
        }, defaultBrightHubUuid);

        nodes.push({
          id: nodeId,
          type: "operationNode",
          position: {
            x: lane.position.x + 80,
            y: 320 + laneIndex * 120,
          },
          data: {
            kind: "operation",
            laneId: step.laneId,
            label: nodeTemplate.label,
            description: nodeTemplate.description,
            category: nodeTemplate.category,
            status: "idle",
            stale: false,
            branchColor,
            templateId: nodeTemplate.id,
            summary: nodeTemplate.fields.length
              ? `${nodeTemplate.fields.length} configurable field${nodeTemplate.fields.length === 1 ? "" : "s"}`
              : "No parameters required",
            fields: nodeTemplate.fields,
            config,
          },
        });

        if (previousNodeId) {
          edges.push(
            createDataFlowEdge(
              previousNodeId,
              nodeId,
              branchColor,
              `${template.id}-edge-${previousNodeId}-${nodeId}`,
            ),
          );
        }
        previousNodeId = nodeId;
      }

      set({
        historyPast: {
          ...state.historyPast,
          [branchId]: pushSnapshot(state.historyPast[branchId] ?? [], createBranchSnapshot(branchState)),
        },
        historyFuture: {
          ...state.historyFuture,
          [branchId]: [],
        },
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branchState,
            nodes,
            edges,
          },
        },
      });

      return firstOperationNodeId;
    },
  serializeSnapshot: () => {
    const state = get();
    return {
      version: WORKFLOW_SNAPSHOT_VERSION,
      branches: cloneJson(state.branches.map((branch) => ({ ...branch, sessionId: null }))),
      branchStates: cloneJson(state.branchStates),
      datasets: cloneJson(state.datasets),
    };
  },
  hydrateSnapshot: (snapshot) =>
    set((state) => {
      if (!snapshot || snapshot.version !== WORKFLOW_SNAPSHOT_VERSION || snapshot.branches.length === 0) {
        return {};
      }

      const branches = cloneJson(snapshot.branches);
      const branchStates: Record<string, BranchState> = {};
      for (const branch of branches) {
        const candidate = snapshot.branchStates[branch.id];
        if (candidate) {
          const migrated = stripLegacyGroupNodes({
            nodes: cloneJson(candidate.nodes),
            edges: cloneJson(candidate.edges),
          });

          branchStates[branch.id] = {
            nodes: migrated.nodes,
            edges: migrated.edges,
            viewport: cloneJson(candidate.viewport),
          };
          continue;
        }

        branchStates[branch.id] = {
          nodes: createBaselineNodes(),
          edges: createBaselineEdges(),
          viewport: { x: 0, y: 0, zoom: 0.8 },
        };
      }

      return {
        branches,
        branchStates,
        historyPast: createHistoryIndex(branches),
        historyFuture: createHistoryIndex(branches),
        datasets: cloneJson(snapshot.datasets),
      };
    }),
  addOperationNode: (branchId, templateId, position, defaultBrightHubUuid = null) => {
    const template = nodeTemplateIndex[templateId];
    if (!template) {
      return null;
    }

    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return null;
    }
    const activeBranch = state.branches.find((candidate) => candidate.id === branchId);
    const nextPosition = resolveDropPosition(branch.nodes, position);
    const nodeId = `${templateId}-${branch.nodes.length + 1}`;

    const config = withBrightHubUuidDefaults(templateId, buildTemplateConfig(template), defaultBrightHubUuid);

    const nextNode: WorkflowNode = {
      id: nodeId,
      type: "operationNode",
      position: nextPosition,
      data: {
        kind: "operation",
        laneId: inferLaneIdForTemplate(templateId, template.category) ?? undefined,
        label: template.label,
        description: template.description,
        category: template.category,
        status: "idle",
        stale: false,
        branchColor: activeBranch?.color,
        templateId,
        summary: template.fields.length ? `${template.fields.length} configurable field${template.fields.length === 1 ? "" : "s"}` : "No parameters required",
        fields: template.fields,
        config,
      },
    };

    state.setNodes(branchId, [...branch.nodes, nextNode]);
    return nodeId;
  },
  addDatasetNode: (branchId, datasetId, position) => {
    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return null;
    }
    const activeBranch = state.branches.find((candidate) => candidate.id === branchId);
    const dataset = state.datasets.find((entry) => entry.id === datasetId);
    if (!dataset) {
      return null;
    }

    const nextPosition = resolveDropPosition(branch.nodes, position);
    const nodeId = `dataset-${datasetId}-${branch.nodes.length + 1}`;
    const nextNode: WorkflowNode = {
      id: nodeId,
      type: "datasetNode",
      position: nextPosition,
      data: {
        kind: "dataset",
        laneId: "group-dataset",
        label: dataset.name,
        description: `${dataset.sensor_count} sensors across ${summarizeDatasetRange(dataset)}`,
        status: "done",
        stale: false,
        branchColor: activeBranch?.color,
        summary: `${dataset.coverage_pct.toFixed(1)}% coverage`,
        badge: "Shared dataset",
      },
    };

    state.setNodes(branchId, [...branch.nodes, nextNode]);
    return nodeId;
  },
  connectNodes: (branchId, connection) => {
    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return;
    }
    const activeBranch = state.branches.find((candidate) => candidate.id === branchId);
    const nextEdges = addEdge(
      {
        ...connection,
        type: "dataFlowEdge",
        animated: false,
        markerEnd: { type: MarkerType.ArrowClosed, color: activeBranch?.color },
        style: {
          stroke: activeBranch?.color,
        },
        data: {
          dataKeys: [],
          status: "idle",
        },
      },
      branch.edges,
    ) as WorkflowEdge[];
    state.setEdges(branchId, nextEdges);
  },
  updateNodeConfig: (branchId, nodeId, key, value) => {
    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return;
    }
    const descendants = collectDescendants(nodeId, branch.edges);
    state.setNodes(
      branchId,
      branch.nodes.map((node) => {
        if (node.id === nodeId && node.data.kind === "operation") {
          return {
            ...node,
            data: {
              ...node.data,
              config: {
                ...node.data.config,
                [key]: value,
              },
              status: "idle",
              stale: true,
            },
          };
        }

        if (!descendants.has(node.id) || node.data.kind !== "operation") {
          return node;
        }

        return {
          ...node,
          data: {
            ...node.data,
            status: "idle",
            stale: true,
          },
        };
      }),
    );
  },
  setExecutionMode: (mode) => set({ executionMode: mode }),
  prepareExecution: (branchId, mode, resetStatuses = true) =>
    set((state) => {
      const branch = state.branchStates[branchId];
      if (!branch) {
        return {};
      }
      const nodes: WorkflowNode[] = !resetStatuses
        ? branch.nodes
        : branch.nodes.map((node) => {
            if (node.data.kind !== "operation" && node.data.kind !== "dataset") {
              return node;
            }
            return {
              ...node,
              data: {
                ...node.data,
                status: "pending" as NodeStatus,
                stale: false,
              },
            };
          });

      return {
        executionMode: mode,
        isExecuting: true,
        activeRunId: null,
        executionEvents: [],
        executionError: null,
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branch,
            nodes,
          },
        },
      };
    }),
  applyExecutionEvent: (branchId, event) =>
    set((state) => {
      const branch = state.branchStates[branchId];
      if (!branch) {
        return {};
      }
      const nextStatus = asNodeStatus(event.status ?? undefined);
      const eventNodeId = event.node_id ?? null;

      const nodes: WorkflowNode[] =
        eventNodeId === null || nextStatus === null
          ? branch.nodes
          : branch.nodes.map((node) => {
              if (node.id !== eventNodeId) {
                return node;
              }
              return {
                ...node,
                data: {
                  ...node.data,
                  status: nextStatus,
                  stale: false,
                },
              };
            });

      const edges: WorkflowEdge[] =
        eventNodeId === null || nextStatus === null
          ? branch.edges
          : branch.edges.map((edge) => {
              if (edge.source !== eventNodeId) {
                return edge;
              }
              return {
                ...edge,
                animated: nextStatus === "running",
                data: {
                  ...edge.data,
                  dataKeys: edge.data?.dataKeys ?? [],
                  status: (nextStatus === "running" ? "active" : "done") as "active" | "done",
                },
              };
            });

      const eventType = event.event_type;
      const terminal = eventType === "run_finished" || eventType === "run_cancelled" || eventType === "run_failed";

      return {
        isExecuting: terminal ? false : true,
        activeRunId: event.run_id || state.activeRunId,
        executionEvents: [...state.executionEvents, event].slice(-300),
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branch,
            nodes,
            edges,
          },
        },
      };
    }),
  applyExecutionResult: (branchId, result) =>
    set((state) => {
      const branch = state.branchStates[branchId];
      if (!branch) {
        return {};
      }
      const nodes: WorkflowNode[] = branch.nodes.map((node) => {
        const status = asNodeStatus(result.node_statuses[node.id]);
        if (!status) {
          return node;
        }
        return {
          ...node,
          data: {
            ...node.data,
            status,
            stale: false,
          },
        };
      });

      return {
        isExecuting: false,
        activeRunId: result.run_id,
        executionEvents: [...state.executionEvents, ...result.events].slice(-300),
        branchStates: {
          ...state.branchStates,
          [branchId]: {
            ...branch,
            nodes,
          },
        },
      };
    }),
  setExecutionError: (message) => set({ executionError: message }),
  stopExecution: () => set({ isExecuting: false }),
  clearExecutionEvents: () => set({ executionEvents: [], executionError: null }),
  buildExecutionRequest: (branchId, mode) => {
    const state = get();
    const branch = state.branchStates[branchId];
    if (!branch) {
      return {
        mode: mode ?? state.executionMode,
        nodes: [],
        edges: [],
      };
    }
    return {
      mode: mode ?? state.executionMode,
      nodes: branch.nodes.map((node) => ({
        id: node.id,
        kind: node.data.kind,
        label: node.data.label,
        template_id: node.data.kind === "operation" ? node.data.templateId : undefined,
        config: node.data.kind === "operation" ? toJsonRecord(node.data.config) : {},
        status: node.data.status,
      })),
      edges: branch.edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
      })),
    };
  },
}));