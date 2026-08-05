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

export type WorkflowNodeKind = "group" | "operation" | "dataset" | "fork";

export interface WorkflowNodeData {
  label: string;
  stage: StageKind;
  summary: string;
  templateId: string;
  /** Serialized params matching the backend tool's signature (JSON string). */
  paramsJson: string;
  requiredParams: string[];
  optionalParams: string[];
  executionKind?: WorkflowNodeKind;
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
  executionKind: WorkflowNodeKind = "operation",
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
      executionKind,
    },
  };
}

export interface WorkflowGraphContext {
  /** Wind-speed sensor names in the session (from the sensor inventory). */
  speedSensors?: string[];
  /** Wind-direction sensor names in the session. */
  directionSensors?: string[];
  /** LTC algorithms already run in the session. */
  ltcAlgorithms?: string[];
}

export function createWorkflowGraph(
  config: WindAnalysisConfig,
  capabilities: WorkflowDispatchCapability[],
  context: WorkflowGraphContext = {},
): { nodes: WorkflowCanvasNode[]; edges: WorkflowCanvasEdge[] } {
  const datasetCap = matchCapability(capabilities, "select-dataset", ["dataset"]);
  const cleaningCap = matchCapability(capabilities, "apply_cleaning_rule", ["cleaning"]);
  const exploreCap = matchCapability(capabilities, "list_sensors", ["list", "sensors"]);
  const shearCap = matchCapability(capabilities, "calculate_shear_timeseries", ["shear"]);
  const shearTableCap = matchCapability(capabilities, "build_shear_table", ["shear", "table"]);
  const hubCap = matchCapability(capabilities, "extrapolate_to_hub_height", ["extrapolate", "hub"]);
  const reanalysisHubCap = matchCapability(capabilities, "extrapolate_reanalysis_to_hub", ["extrapolate", "reanalysis", "hub"]);
  const brighthubReanalysisCap = matchCapability(capabilities, "brighthub_prepare_reanalysis", ["brighthub", "reanalysis"]);
  const homogCap = matchCapability(capabilities, "analyze_homogeneity", ["homogeneity"]);
  const ensembleCap = matchCapability(capabilities, "run_ensemble", ["ensemble"]);
  const uncertaintyCap = matchCapability(capabilities, "calculate_uncertainty", ["uncertainty"]);
  const clippingCap = matchCapability(capabilities, "run_clipping_analysis", ["clipping"]);

  // Resolve node params, falling back to live session facts (sensor inventory,
  // completed LTC runs) when the saved config leaves a field empty — so a
  // "rebuild from config" on a finished session produces runnable params.
  const speedSensors = context.speedSensors ?? [];
  const dirSensors = context.directionSensors ?? [];
  const fallbackShort = speedSensors[speedSensors.length - 1] ?? "";
  const hubHeightLabel = String(config.site.hubHeightM);
  const fallbackLong = `Spd_${hubHeightLabel}m_hub`;

  const datasetId = config.inputs.sharedDatasetId;
  const shearPair =
    config.shear.speedSensorPair.length > 0 ? config.shear.speedSensorPair : speedSensors;
  const heightSensors = shearPair.length > 0 ? JSON.stringify(shearPair) : "";
  const ltcShortCol = config.ltc.shortColumn || fallbackShort;
  const ltcLongCol = config.ltc.longColumn || fallbackLong;
  const ltcShortDirCol = config.ltc.shortDirectionColumn || dirSensors[dirSensors.length - 1] || "";
  const ltcLongDirCol = config.ltc.longDirectionColumn || (ltcShortDirCol ? "ERA5_Direction" : "");
  const measuredCol = config.ltc.measuredColumn || ltcShortCol;
  const algorithmsRun = context.ltcAlgorithms ?? [];
  const ltcAlgorithms = config.ltc.algorithms.filter((algorithm) => algorithm !== "ensemble");
  const selectedLtcAlgorithms = ltcAlgorithms.length > 0 ? ltcAlgorithms : ["speedsort"];
  const useEnsembleForClipping = selectedLtcAlgorithms.length > 1 || algorithmsRun.length > 1;
  const clippingSource = useEnsembleForClipping ? "ensemble" : algorithmsRun[0] ?? selectedLtcAlgorithms[0];
  const clippingSpeedCol = useEnsembleForClipping ? "Ensemble_Speed" : `${clippingSource}_Speed`;
  const cleaningRule = config.cleaning.rules[0];

  const ltcNodes = selectedLtcAlgorithms.map((algorithm, index) => {
    const id = selectedLtcAlgorithms.length === 1 ? "ltc" : `ltc_${algorithm}`;
    const capability = matchCapability(capabilities, `run_ltc_${algorithm}`, ["ltc", algorithm]);
    return buildNode(
      id,
      { x: 1120, y: 50 + index * 160 },
      "ltc",
      `LTC · ${algorithm.replaceAll("_", " ")}`,
      "Measured hub-height and ERA5 reference",
      capability,
      {
        short_col: ltcShortCol,
        long_col: ltcLongCol,
        short_dir_col: ltcShortDirCol,
        long_dir_col: ltcLongDirCol,
      },
    );
  });

  const nodes: WorkflowCanvasNode[] = [
    buildNode("dataset", { x: 0, y: 40 }, "dataset", "Dataset intake", datasetId || "Upload/import data", datasetCap, { dataset_id: datasetId }, "dataset"),
    buildNode(
      "cleaning",
      { x: 280, y: 40 },
      "cleaning",
      "Cleaning",
      cleaningRule ? `${config.cleaning.rules.length} rule(s)` : "Manual review",
      cleaningRule ? cleaningCap : undefined,
      cleaningRule
        ? { rule_type: cleaningRule.ruleType, sensor: cleaningRule.sensor, params: cleaningRule.params, start_date: cleaningRule.startDate, end_date: cleaningRule.endDate }
        : {},
      cleaningRule ? "operation" : "group",
    ),
    buildNode("explore", { x: 280, y: 220 }, "explore", "Explore stats", "List sensors & coverage", exploreCap, {}),
    buildNode("shear", { x: 560, y: 40 }, "shear", "Shear timeseries", `${config.shear.method} · aggregation ${config.shear.aggregation}`, shearCap, { height_sensors: heightSensors }),
    buildNode("shear_table", { x: 560, y: 220 }, "shear", "Shear table", `12×24 · ${config.shear.aggregation}`, shearTableCap, { aggregation: config.shear.aggregation }),
    buildNode("extrapolate_hub", { x: 840, y: 130 }, "extrapolate_hub", "Extrapolate → hub", `${config.site.hubHeightM}m · ${config.shear.method}`, hubCap, { hub_height_m: config.site.hubHeightM, shear_model: config.shear.method }),
    buildNode(
      "brighthub_reanalysis",
      { x: 280, y: 400 },
      "era5_extract",
      "BrightHub ERA5 + MERRA-2",
      "Authenticated download and ERA5 site interpolation",
      brighthubReanalysisCap,
      { latitude: config.reanalysis.searchLatitude, longitude: config.reanalysis.searchLongitude, source: "brighthub" },
    ),
    buildNode(
      "extrapolate_reanalysis_hub",
      { x: 840, y: 400 },
      "extrapolate_hub",
      "ERA5 → hub",
      `${config.site.hubHeightM}m reference series`,
      reanalysisHubCap,
      { hub_height_m: config.site.hubHeightM },
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
    ...ltcNodes,
    buildNode(
      "ensemble",
      { x: 1400, y: 40 },
      "ensemble",
      "Ensemble",
      "Inverse-RMSE blend",
      ensembleCap,
      { measured_col: measuredCol },
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
      { speed_col: clippingSpeedCol, source: clippingSource },
    ),
  ];

  const edges: WorkflowCanvasEdge[] = [
    { id: "dataset-cleaning", source: "dataset", target: "cleaning", type: "smoothstep" },
    { id: "dataset-explore", source: "dataset", target: "explore", type: "smoothstep" },
    { id: "cleaning-shear", source: "cleaning", target: "shear", type: "smoothstep" },
    { id: "shear-shear_table", source: "shear", target: "shear_table", type: "smoothstep" },
    { id: "shear_table-extrapolate_hub", source: "shear_table", target: "extrapolate_hub", type: "smoothstep" },
    { id: "dataset-brighthub_reanalysis", source: "dataset", target: "brighthub_reanalysis", type: "smoothstep" },
    { id: "brighthub_reanalysis-homogeneity", source: "brighthub_reanalysis", target: "homogeneity", type: "smoothstep" },
    { id: "shear_table-extrapolate_reanalysis_hub", source: "shear_table", target: "extrapolate_reanalysis_hub", type: "smoothstep" },
    { id: "brighthub_reanalysis-extrapolate_reanalysis_hub", source: "brighthub_reanalysis", target: "extrapolate_reanalysis_hub", type: "smoothstep" },
    ...ltcNodes.flatMap((node) => [
      { id: `extrapolate_hub-${node.id}`, source: "extrapolate_hub", target: node.id, type: "smoothstep" },
      { id: `extrapolate_reanalysis_hub-${node.id}`, source: "extrapolate_reanalysis_hub", target: node.id, type: "smoothstep" },
      { id: `${node.id}-ensemble`, source: node.id, target: "ensemble", type: "smoothstep" },
    ]),
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
  kind: WorkflowNodeKind;
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
      kind: node.data.executionKind ?? (index === 0 ? "dataset" : "operation"),
      label: node.data.label,
      template_id: node.data.templateId || null,
      config: decodeParams(node.data.paramsJson),
      status: null,
    })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
  };
}
