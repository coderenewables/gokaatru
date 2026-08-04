import { describe, expect, it } from "vitest";

import { createWorkflowGraph, toExecutionRequest } from "../lib/workflow";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import type { WorkflowDispatchCapability } from "../types/analysis";

const CAPABILITIES: WorkflowDispatchCapability[] = [
  { template_id: "select-dataset", required_params: [], optional_params: [] },
  { template_id: "apply_cleaning_rule", required_params: ["rule_type"], optional_params: ["sensor", "params"] },
  { template_id: "list_sensors", required_params: [], optional_params: [] },
  { template_id: "calculate_shear_timeseries", required_params: ["height_sensors"], optional_params: [] },
  { template_id: "build_shear_table", required_params: [], optional_params: ["aggregation"] },
  { template_id: "extrapolate_to_hub_height", required_params: ["hub_height_m"], optional_params: ["shear_model"] },
  { template_id: "extrapolate_reanalysis_to_hub", required_params: ["hub_height_m"], optional_params: ["reference_height_m"] },
  { template_id: "brighthub_prepare_reanalysis", required_params: ["latitude", "longitude"], optional_params: [] },
  { template_id: "analyze_homogeneity", required_params: [], optional_params: ["method"] },
  { template_id: "run_ltc_speedsort", required_params: ["short_col", "long_col"], optional_params: ["short_dir_col", "long_dir_col"] },
  { template_id: "run_ltc_linear_least_squares", required_params: ["short_col", "long_col"], optional_params: [] },
  { template_id: "run_ltc_variance_ratio", required_params: ["short_col", "long_col"], optional_params: [] },
  { template_id: "run_ensemble", required_params: ["measured_col"], optional_params: [] },
  { template_id: "calculate_uncertainty", required_params: ["measurement_uncertainty_pct"], optional_params: [] },
  { template_id: "run_clipping_analysis", required_params: ["speed_col"], optional_params: ["source"] },
];

describe("createWorkflowGraph", () => {
  it("emits the default DAG with a BrightHub reanalysis node", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const ids = nodes.map((n) => n.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "dataset",
        "cleaning",
        "explore",
        "shear",
        "shear_table",
        "extrapolate_hub",
        "brighthub_reanalysis",
        "extrapolate_reanalysis_hub",
        "homogeneity",
        "ltc",
        "ensemble",
        "uncertainty",
        "clipping",
      ]),
    );
    // The dataset → cleaning → shear → ltc → ensemble chain exists.
    const edgeKeys = new Set(edges.map((e) => `${e.source}->${e.target}`));
    expect(edgeKeys.has("dataset->cleaning")).toBe(true);
    expect(edgeKeys.has("cleaning->shear")).toBe(true);
    expect(edgeKeys.has("extrapolate_hub->ltc")).toBe(true);
    expect(edgeKeys.has("extrapolate_reanalysis_hub->ltc")).toBe(true);
    expect(edgeKeys.has("ltc->ensemble")).toBe(true);
    expect(edgeKeys.has("ensemble->uncertainty")).toBe(true);
  });

  it("matches template_ids to backend capabilities when available", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes } = createWorkflowGraph(config, CAPABILITIES);
    const shear = nodes.find((n) => n.id === "shear");
    const ltc = nodes.find((n) => n.id === "ltc");
    const dataset = nodes.find((n) => n.id === "dataset");
    expect(shear?.data.templateId).toBe("calculate_shear_timeseries");
    expect(ltc?.data.templateId).toBe("run_ltc_speedsort");
    expect(dataset?.data.templateId).toBe("select-dataset");
  });

  it("leaves templateId empty when no capability matches", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes } = createWorkflowGraph(config, []);
    const dataset = nodes.find((n) => n.id === "dataset");
    expect(dataset?.data.templateId).toBe("");
  });

  it("serializes config slices into paramsJson", () => {
    const config = createDefaultWindAnalysisConfig();
    config.shear.speedSensorPair = ["Spd_80m", "Spd_120m"];
    const { nodes } = createWorkflowGraph(config, CAPABILITIES);
    const shear = nodes.find((n) => n.id === "shear");
    const params = JSON.parse(shear?.data.paramsJson ?? "{}");
    expect(params.height_sensors).toBe(JSON.stringify(["Spd_80m", "Spd_120m"]));
  });

  it("creates linear-least-squares and variance-ratio branches before the ensemble", () => {
    const config = createDefaultWindAnalysisConfig();
    config.ltc.algorithms = ["linear_least_squares", "variance_ratio"];
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edgeKeys = new Set(edges.map((edge) => `${edge.source}->${edge.target}`));

    expect(nodeById.get("ltc_linear_least_squares")?.data.templateId).toBe("run_ltc_linear_least_squares");
    expect(nodeById.get("ltc_variance_ratio")?.data.templateId).toBe("run_ltc_variance_ratio");
    expect(edgeKeys).toContain("extrapolate_hub->ltc_linear_least_squares");
    expect(edgeKeys).toContain("extrapolate_reanalysis_hub->ltc_variance_ratio");
    expect(edgeKeys).toContain("ltc_linear_least_squares->ensemble");
    expect(edgeKeys).toContain("ltc_variance_ratio->ensemble");

    const clipping = nodeById.get("clipping");
    expect(JSON.parse(clipping?.data.paramsJson ?? "{}")).toMatchObject({
      source: "ensemble",
      speed_col: "Ensemble_Speed",
    });
  });
});

describe("toExecutionRequest", () => {
  it("marks the dataset, manual-review, and executable node kinds", () => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const req = toExecutionRequest(nodes, edges, "auto");
    expect(req.mode).toBe("auto");
    expect(req.nodes[0].kind).toBe("dataset");
    expect(req.nodes[1].kind).toBe("group");
    expect(req.nodes[2].kind).toBe("operation");
    expect(req.edges.length).toBe(edges.length);
  });

  it("decodes paramsJson into config objects", () => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const req = toExecutionRequest(nodes, edges, "manual");
    const extrapolate = req.nodes.find((n) => n.id === "extrapolate_hub");
    expect(extrapolate?.config).toMatchObject({ hub_height_m: 150 });
  });

  it("keeps a no-rule cleaning node as a manual-review group", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const req = toExecutionRequest(nodes, edges, "auto");

    expect(req.nodes.find((node) => node.id === "cleaning")?.kind).toBe("group");
  });

  it("tolerates malformed paramsJson", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    // Corrupt one node's params.
    nodes[0].data.paramsJson = "not-json{";
    const req = toExecutionRequest(nodes, edges, "auto");
    expect(req.nodes[0].config).toEqual({});
  });
});
