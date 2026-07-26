// React Flow graph builder for the 8-stage workflow (spec §5).
//
// Maps the typed WindAnalysisConfig + backend dispatch capabilities into a DAG
// of nodes/edges that the backend WorkflowExecutor can run topologically. Each
// node carries a template_id (backend tool name) + paramsJson (serialized args).
import type { Edge, Node } from "@xyflow/react";

import type {
  WindAnalysisConfig,
  WorkflowDispatchCapability,
} from "../types/analysis";

// ---------------------------------------------------------------------------
// Canvas node/edge types
// ---------------------------------------------------------------------------

export type StageKind =
  | "dataset"
  | "cleaning"
  | "explore"
  | "shear"
  | "extrapolate_hub"
  | "era5_nodes"
  | "era5_extract"
  | "era5_interpolate"
  | "homogeneity"
  | "ltc"
  | "ensemble"
  | "uncertainty"
  | "clipping";

export interface WorkflowNodeData {
  label: string;
  stage: StageKind;
  summary: string;
  templateId: string;
  /** Serialized params matching the backend tool's signature (JSON string). */
  paramsJson: string;
  requiredParams: string[];
  optionalParams: string[];
  [key: string]: unknown;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData>;
export type WorkflowCanvasEdge = Edge;

// ---------------------------------------------------------------------------
// Capability matching
// ---------------------------------------------------------------------------

function matchCapability(
  capabilities: WorkflowDispatchCapability[],
  exactId: string,
  fuzzyTokens: string[],
): WorkflowDispatchCapability | undefined {
  const exact = capabilities.find((c) => c.template_id === exactId);
  if (exact) return exact;
  return capabilities.find((c) => fuzzyTokens.every((t) => c.template_id.includes(t)));
}

// ---------------------------------------------------------------------------
// Graph construction
// ---------------------------------------------------------------------------

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function buildNode(
  id: string,
  position: { x: number; y: number },
  stage: StageKind,
  label: string,
  summary: string,
  capability: WorkflowDispatchCapability | undefined,
  params: unknown,
): WorkflowCanvasNode {
  return {
    id,
    type: "stageNode",
    position,
    data: {
      label,
      stage,
      summary,
      templateId: capability?.template_id ?? "",
      paramsJson: prettyJson(params),
      requiredParams: capability?.required_params ?? [],
      optionalParams: capability?.optional_params ?? [],
    },
  };
}

export function createWorkflowGraph(
  config: WindAnalysisConfig,
  capabilities: WorkflowDispatchCapability[],
): { nodes: WorkflowCanvasNode[]; edges: WorkflowCanvasEdge[] } {
  const datasetCap = matchCapability(capabilities, "select-dataset", ["dataset"]);
  const cleaningCap = matchCapability(capabilities, "apply_cleaning_rule", ["cleaning"]);
  const exploreCap = matchCapability(capabilities, "list_sensors", ["list", "sensors"]);
  const shearCap = matchCapability(capabilities, "calculate_shear_timeseries", ["shear"]);
  const shearTableCap = matchCapability(capabilities, "build_shear_table", ["shear", "table"]);
  const hubCap = matchCapability(capabilities, "extrapolate_to_hub_height", ["extrapolate", "hub"]);
  const era5NodesCap = matchCapability(capabilities, "find_era5_nodes", ["era5", "nodes"]);
  const era5ExtractCap = matchCapability(capabilities, "extract_era5_data", ["era5", "extract"]);
  const era5InterpCap = matchCapability(capabilities, "interpolate_era5_to_site", ["era5", "interpolate"]);
  const homogCap = matchCapability(capabilities, "analyze_homogeneity", ["homogeneity"]);
  const ltcCap = matchCapability(capabilities, "run_ltc_speedsort", ["ltc"]);
  const ensembleCap = matchCapability(capabilities, "run_ensemble", ["ensemble"]);
  const uncertaintyCap = matchCapability(capabilities, "calculate_uncertainty", ["uncertainty"]);
  const clippingCap = matchCapability(capabilities, "run_clipping_analysis", ["clipping"]);

  const heightSensors =
    config.shear.speedSensorPair.length > 0
      ? JSON.stringify(config.shear.speedSensorPair)
      : "";

  const nodes: WorkflowCanvasNode[] = [
    buildNode(
      "dataset",
      { x: 0, y: 40 },
      "dataset",
      "Dataset intake",
      config.inputs.sharedDatasetId || "Upload/import data",
      datasetCap,
      { dataset_id: config.inputs.sharedDatasetId },
    ),
    buildNode(
      "cleaning",
      { x: 280, y: 40 },
      "cleaning",
      "Cleaning",
      `${config.cleaning.rules.length} rule(s)`,
      cleaningCap,
      config.cleaning.rules[0] ?? { rule_type: "range_check", sensor: "", params: {} },
    ),
    buildNode(
      "explore",
      { x: 280, y: 220 },
      "explore",
      "Explore stats",
      "List sensors & coverage",
      exploreCap,
      {},
    ),
    buildNode(
      "shear",
      { x: 560, y: 40 },
      "shear",
      "Shear timeseries",
      `${config.shear.method} · aggregation ${config.shear.aggregation}`,
      shearCap,
      { height_sensors: heightSensors },
    ),
    buildNode(
      "shear_table",
      { x: 560, y: 220 },
      "shear",
      "Shear table",
      `12×24 · ${config.shear.aggregation}`,
      shearTableCap,
      { aggregation: config.shear.aggregation },
    ),
    buildNode(
      "extrapolate_hub",
      { x: 840, y: 130 },
      "extrapolate_hub",
      "Extrapolate → hub",
      `${config.site.hubHeightM}m · ${config.shear.method}`,
      hubCap,
      { hub_height_m: config.site.hubHeightM, shear_model: config.shear.method },
    ),
    buildNode(
      "era5_nodes",
      { x: 0, y: 300 },
      "era5_nodes",
      "ERA5 nodes",
      `lat ${config.reanalysis.searchLatitude}, lon ${config.reanalysis.searchLongitude}`,
      era5NodesCap,
      {
        latitude: config.reanalysis.searchLatitude,
        longitude: config.reanalysis.searchLongitude,
      },
    ),
    buildNode(
      "era5_extract",
      { x: 280, y: 400 },
      "era5_extract",
      "ERA5 extract",
      `${config.reanalysis.startDate} → ${config.reanalysis.endDate}`,
      era5ExtractCap,
      {
        latitude: config.reanalysis.searchLatitude,
        longitude: config.reanalysis.searchLongitude,
        start_date: config.reanalysis.startDate,
        end_date: config.reanalysis.endDate,
      },
    ),
    buildNode(
      "era5_interpolate",
      { x: 560, y: 400 },
      "era5_interpolate",
      "ERA5 interpolate",
      "Interpolate to site",
      era5InterpCap,
      {},
    ),
    buildNode(
      "homogeneity",
      { x: 840, y: 320 },
      "homogeneity",
      "Homogeneity",
      "Pettitt annual test (optional)",
      homogCap,
      { method: "annual" },
    ),
    buildNode(
      "ltc",
      { x: 1120, y: 130 },
      "ltc",
      "LTC",
      `${config.ltc.algorithms.join(", ") || "no algorithms"}`,
      ltcCap,
      {
        short_col: config.ltc.shortColumn,
        long_col: config.ltc.longColumn,
        short_dir_col: config.ltc.shortDirectionColumn,
        long_dir_col: config.ltc.longDirectionColumn,
      },
    ),
    buildNode(
      "ensemble",
      { x: 1400, y: 40 },
      "ensemble",
      "Ensemble",
      "Inverse-RMSE blend",
      ensembleCap,
      { measured_col: config.ltc.measuredColumn || config.ltc.shortColumn },
    ),
    buildNode(
      "uncertainty",
      { x: 1400, y: 220 },
      "uncertainty",
      "Uncertainty",
      `IAV ${config.ltc.uncertainty.iavPct}%`,
      uncertaintyCap,
      {
        measurement_uncertainty_pct: config.ltc.uncertainty.measurementUncertaintyPct,
        measurement_height_m: config.ltc.uncertainty.measurementHeightM,
        hub_height_m: config.ltc.uncertainty.hubHeightM,
        shear_method: config.ltc.uncertainty.shearMethod,
        mcp_r_squared: config.ltc.uncertainty.mcpRSquared,
        concurrent_hours: config.ltc.uncertainty.concurrentHours,
        algorithm: config.ltc.uncertainty.algorithm,
        iav_pct: config.ltc.uncertainty.iavPct,
        shear_std: config.ltc.uncertainty.shearStd,
        is_interpolation: config.ltc.uncertainty.isInterpolation,
      },
    ),
    buildNode(
      "clipping",
      { x: 1120, y: 320 },
      "clipping",
      "Clipping",
      "Representative period",
      clippingCap,
      { speed_col: "Ensemble_Speed", source: "ensemble" },
    ),
  ];

  const edges: WorkflowCanvasEdge[] = [
    { id: "dataset-cleaning", source: "dataset", target: "cleaning", type: "smoothstep" },
    { id: "dataset-explore", source: "dataset", target: "explore", type: "smoothstep" },
    { id: "cleaning-shear", source: "cleaning", target: "shear", type: "smoothstep" },
    { id: "shear-shear_table", source: "shear", target: "shear_table", type: "smoothstep" },
    { id: "shear_table-extrapolate_hub", source: "shear_table", target: "extrapolate_hub", type: "smoothstep" },
    { id: "dataset-era5_nodes", source: "dataset", target: "era5_nodes", type: "smoothstep" },
    { id: "era5_nodes-era5_extract", source: "era5_nodes", target: "era5_extract", type: "smoothstep" },
    { id: "era5_extract-era5_interpolate", source: "era5_extract", target: "era5_interpolate", type: "smoothstep" },
    { id: "era5_interpolate-homogeneity", source: "era5_interpolate", target: "homogeneity", type: "smoothstep" },
    { id: "extrapolate_hub-ltc", source: "extrapolate_hub", target: "ltc", type: "smoothstep" },
    { id: "era5_interpolate-ltc", source: "era5_interpolate", target: "ltc", type: "smoothstep" },
    { id: "ltc-ensemble", source: "ltc", target: "ensemble", type: "smoothstep" },
    { id: "ensemble-uncertainty", source: "ensemble", target: "uncertainty", type: "smoothstep" },
    { id: "ensemble-clipping", source: "ensemble", target: "clipping", type: "smoothstep" },
  ];

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Execution serializer
// ---------------------------------------------------------------------------

export interface ExecutionNodePayload {
  id: string;
  kind: "group" | "operation" | "dataset" | "fork";
  label: string;
  template_id: string | null;
  config: Record<string, unknown>;
  status: string | null;
}

export interface ExecutionRequest {
  mode: "auto" | "manual";
  nodes: ExecutionNodePayload[];
  edges: Array<{ source: string; target: string }>;
}

function decodeParams(paramsJson: string): Record<string, unknown> {
  if (!paramsJson) return {};
  try {
    const parsed = JSON.parse(paramsJson);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    /* ignore malformed */
  }
  return {};
}

export function toExecutionRequest(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  mode: "auto" | "manual",
): ExecutionRequest {
  return {
    mode,
    nodes: nodes.map((node, index) => ({
      id: node.id,
      kind: index === 0 ? ("dataset" as const) : ("operation" as const),
      label: node.data.label,
      template_id: node.data.templateId || null,
      config: decodeParams(node.data.paramsJson),
      status: null,
    })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
  };
}
