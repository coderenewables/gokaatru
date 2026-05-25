import { createWorkflowGraph, toExecutionRequest } from "../lib/workflow";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";

describe("workflow graph", () => {
  it("builds a connected stage graph from the typed config", () => {
    const graph = createWorkflowGraph(createDefaultWindAnalysisConfig(), []);

    expect(graph.nodes.map((node) => node.id)).toEqual([
      "dataset",
      "cleaning",
      "shear",
      "reanalysis",
      "ltc",
      "windkit",
    ]);
    expect(graph.edges).toHaveLength(6);
  });

  it("serializes workflow node params into the execution request shape", () => {
    const graph = createWorkflowGraph(createDefaultWindAnalysisConfig(), []);
    const request = toExecutionRequest(graph.nodes, graph.edges, "manual");

    expect(request.mode).toBe("manual");
    expect(request.nodes[0].kind).toBe("dataset");
    expect(request.edges[0]).toEqual({ source: "dataset", target: "cleaning" });
  });
});