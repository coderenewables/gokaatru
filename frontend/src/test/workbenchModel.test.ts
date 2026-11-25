import { afterEach, describe, expect, it } from "vitest";

import { COLUMN_WIDTH, ROW_HEIGHT, layoutSteps, portsOf } from "../workbench/model/graph";
import { type OperationInfo, paletteOf } from "../workbench/model/operations";
import { newStepId, pipelineKey, usePipeline } from "../workbench/model/store";

const step = (id: string, operation = id) => ({ id, operation, parameters: {} });

function operation(name: string, stage: string, extra: Partial<OperationInfo> = {}): OperationInfo {
  return {
    name, stage, description: "", effect: "change", canvas: true, network: false, disclosure: [], standards: [],
    dry_run: false, selectable: false, reads: [], writes: [], parameters: {}, ...extra,
  };
}

describe("laying out the pipeline", () => {
  it("puts a step one column after everything it reads from, rows in the server's order", () => {
    const steps = [step("ltc"), step("series"), step("table"), step("hub"), step("weibull")];
    const edges = [
      { source: "series", target: "table", artifact: "shear_timeseries" },
      { source: "table", target: "hub", artifact: "shear_table" },
      { source: "hub", target: "ltc", artifact: "hub_height_series" },
    ];
    const placed = layoutSteps(steps, ["series", "weibull", "table", "hub", "ltc"], edges);
    expect(placed.series).toEqual({ x: 20, y: 20 });
    expect(placed.weibull).toEqual({ x: 20, y: 20 + ROW_HEIGHT });
    expect(placed.table.x).toBe(20 + COLUMN_WIDTH);
    expect(placed.ltc.x).toBe(20 + 3 * COLUMN_WIDTH);
  });

  it("keeps a step where it was moved", () => {
    const placed = layoutSteps([{ ...step("series"), position: { x: 400, y: 9 } }], ["series"], []);
    expect(placed.series).toEqual({ x: 400, y: 9 });
  });

  it("draws as ports only what another step writes", () => {
    expect(portsOf("hub", { shear_table: ["table"], measured_data: [], settings: [] })).toEqual({
      fromSteps: ["shear_table"],
      fromSession: ["measured_data", "settings"],
    });
  });
});

describe("the palette", () => {
  it("offers the Model stages' canvas operations without network ones, changes first", () => {
    const stages = paletteOf([
      operation("parse_timeseries", "ingest"),
      operation("compute_vertical_structure", "shear", { effect: "read" }),
      operation("build_shear_table", "shear"),
      operation("brighthub_login", "reanalysis_download", { network: true }),
      operation("undo_last_change", "config", { canvas: false }),
      operation("run_ensemble", "ensemble"),
    ]);
    expect([...stages.keys()]).toEqual(["shear", "ensemble"]);
    expect(stages.get("shear")?.map((entry) => entry.name)).toEqual(["build_shear_table", "compute_vertical_structure"]);
  });
});

describe("the pipeline store", () => {
  afterEach(() => {
    window.localStorage.clear();
    usePipeline.setState({ sessionId: null, steps: [], selected: null, runs: {} });
  });

  it("names a step from its operation, uniquely", () => {
    expect(newStepId("run_ltc_variance_ratio", [])).toBe("variance_ratio");
    expect(newStepId("build_shear_table", [step("shear_table")])).toBe("shear_table-2");
  });

  it("keeps each campaign's pipeline in this browser, apart from the others", () => {
    const store = usePipeline.getState();
    store.open("a");
    usePipeline.getState().add("build_shear_table");
    usePipeline.getState().add("extrapolate_to_hub_height", { hub_height_m: 120 });
    expect(JSON.parse(window.localStorage.getItem(pipelineKey("a")) ?? "[]")).toHaveLength(2);

    usePipeline.getState().open("b");
    expect(usePipeline.getState().steps).toEqual([]);
    usePipeline.getState().open("a");
    expect(usePipeline.getState().steps.map((entry) => entry.id)).toEqual(["shear_table", "extrapolate_to_hub_height"]);

    usePipeline.getState().remove("shear_table");
    expect(JSON.parse(window.localStorage.getItem(pipelineKey("a")) ?? "[]")).toHaveLength(1);
  });
});
