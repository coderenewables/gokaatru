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
  { template_id: "find_era5_nodes", required_params: ["latitude", "longitude"], optional_params: [] },
  { template_id: "extract_era5_data", required_params: ["latitude", "longitude"], optional_params: ["start_date", "end_date"] },
  { template_id: "interpolate_era5_to_site", required_params: [], optional_params: [] },
  { template_id: "analyze_homogeneity", required_params: [], optional_params: ["method"] },
  { template_id: "run_ltc_speedsort", required_params: ["short_col", "long_col"], optional_params: ["short_dir_col", "long_dir_col"] },
  { template_id: "run_ensemble", required_params: ["measured_col"], optional_params: [] },
  { template_id: "calculate_uncertainty", required_params: ["measurement_uncertainty_pct"], optional_params: [] },
  { template_id: "run_clipping_analysis", required_params: ["speed_col"], optional_params: ["source"] },
];

describe("createWorkflowGraph", () => {
  it("emits the full 14-node DAG with the expected node ids", () => {
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
        "era5_nodes",
        "era5_extract",
        "era5_interpolate",
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
    expect(edgeKeys.has("era5_interpolate->ltc")).toBe(true);
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
});

describe("toExecutionRequest", () => {
  it("marks the first node as dataset and the rest as operation", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const req = toExecutionRequest(nodes, edges, "auto");
    expect(req.mode).toBe("auto");
    expect(req.nodes[0].kind).toBe("dataset");
    expect(req.nodes[1].kind).toBe("operation");
    expect(req.edges.length).toBe(edges.length);
  });

  it("decodes paramsJson into config objects", () => {
    const config = createDefaultWindAnalysisConfig();
    const { nodes, edges } = createWorkflowGraph(config, CAPABILITIES);
    const req = toExecutionRequest(nodes, edges, "manual");
    const extrapolate = req.nodes.find((n) => n.id === "extrapolate_hub");
    expect(extrapolate?.config).toMatchObject({ hub_height_m: 120 });
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
