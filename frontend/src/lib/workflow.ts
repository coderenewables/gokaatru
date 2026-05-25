import type { Edge, Node } from "@xyflow/react";

import type { WorkflowDispatchCapability } from "./api";
import type { WindAnalysisConfig } from "../types/analysis";

export interface WorkflowNodeData {
  [key: string]: unknown;
  label: string;
  stage: string;
  summary: string;
  templateId: string;
  paramsJson: string;
  requiredParams: string[];
  optionalParams: string[];
}

export type WorkflowCanvasNode = Node<WorkflowNodeData>;
export type WorkflowCanvasEdge = Edge;

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function matchCapability(capabilities: WorkflowDispatchCapability[], exactId: string, fuzzyTokens: string[]): WorkflowDispatchCapability | undefined {
  const exact = capabilities.find((capability) => capability.template_id === exactId);
  if (exact) {
    return exact;
  }
  return capabilities.find((capability) => fuzzyTokens.every((token) => capability.template_id.includes(token)));
}

function buildNode(
  id: string,
  position: { x: number; y: number },
  stage: string,
  summary: string,
  capability: WorkflowDispatchCapability | undefined,
  params: unknown,
): WorkflowCanvasNode {
  return {
    id,
    type: "default",
    position,
    data: {
      label: stage,
      stage: id,
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
  const datasetCapability = matchCapability(capabilities, "select-dataset", ["dataset"]);
  const cleaningCapability = matchCapability(capabilities, "apply_cleaning_rule", ["cleaning"]);
  const shearCapability = matchCapability(capabilities, "calculate_shear_timeseries", ["shear"]);
  const reanalysisCapability = matchCapability(capabilities, "find_era5_nodes", ["era5"]);
  const ltcCapability = matchCapability(capabilities, "run_ltc_speedsort", ["ltc"]);
  const windkitCapability = matchCapability(capabilities, "windkit_wind_speed", ["windkit", "wind"]);

  const nodes: WorkflowCanvasNode[] = [
    buildNode(
      "dataset",
      { x: 40, y: 60 },
      "Dataset intake",
      config.inputs.sharedDatasetId || "Select a shared dataset or upload files",
      datasetCapability,
      { dataset_id: config.inputs.sharedDatasetId },
    ),
    buildNode(
      "cleaning",
      { x: 330, y: 60 },
      "Cleaning",
      `${config.cleaning.rules.length} configured rule(s)`,
      cleaningCapability,
      config.cleaning.rules[0] ?? { rule_type: "range_filter", sensor: "", params: {} },
    ),
    buildNode(
      "shear",
      { x: 620, y: 60 },
      "Shear and hub height",
      `${config.shear.method} to ${config.shear.targetHubHeightM}m`,
      shearCapability,
      {
        height_sensors: config.shear.speedSensorPair.join(","),
        aggregation: config.shear.aggregation,
      },
    ),
    buildNode(
      "reanalysis",
      { x: 330, y: 260 },
      "Reanalysis",
      `${config.reanalysis.preferredProvider} ${config.reanalysis.startDate} → ${config.reanalysis.endDate}`,
      reanalysisCapability,
      {
        latitude: config.reanalysis.searchLatitude,
        longitude: config.reanalysis.searchLongitude,
        start_date: config.reanalysis.startDate,
        end_date: config.reanalysis.endDate,
      },
    ),
    buildNode(
      "ltc",
      { x: 620, y: 260 },
      "LTC and uncertainty",
      `${config.ltc.algorithms.join(", ")} · ${config.ltc.shortColumn || "short"} vs ${config.ltc.longColumn || "long"}`,
      ltcCapability,
      {
        short_col: config.ltc.shortColumn,
        long_col: config.ltc.longColumn,
        short_dir_col: config.ltc.shortDirectionColumn,
        long_dir_col: config.ltc.longDirectionColumn,
      },
    ),
    buildNode(
      "windkit",
      { x: 910, y: 160 },
      "WindKit bridge",
      `${config.windkit.enabledCategories.length} categories available`,
      windkitCapability,
      { u: [5, 6, 7], v: [1, 1, 0] },
    ),
  ];

  const edges: WorkflowCanvasEdge[] = [
    { id: "dataset-cleaning", source: "dataset", target: "cleaning" },
    { id: "cleaning-shear", source: "cleaning", target: "shear" },
    { id: "dataset-reanalysis", source: "dataset", target: "reanalysis" },
    { id: "shear-ltc", source: "shear", target: "ltc" },
    { id: "reanalysis-ltc", source: "reanalysis", target: "ltc" },
    { id: "ltc-windkit", source: "ltc", target: "windkit" },
  ];

  return { nodes, edges };
}

export function toExecutionRequest(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  mode: "auto" | "manual",
) {
  return {
    mode,
    nodes: nodes.map((node, index) => {
      let decodedParams: Record<string, unknown> = {};
      try {
        const maybeObject = JSON.parse(node.data.paramsJson || "{}");
        if (typeof maybeObject === "object" && maybeObject !== null && !Array.isArray(maybeObject)) {
          decodedParams = maybeObject as Record<string, unknown>;
        }
      } catch {
        decodedParams = {};
      }

      return {
        id: node.id,
        kind: index === 0 ? "dataset" : "operation",
        label: node.data.label,
        template_id: node.data.templateId || null,
        config: decodedParams,
        status: null,
      };
    }),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
  };
}
