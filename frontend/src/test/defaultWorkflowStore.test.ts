import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultWorkflowConfig } from "../lib/defaultWorkflowPlan";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { serializeConfigToRunconfig } from "../lib/configSync";
import type { SensorRow, WorkflowDispatchCapability } from "../types/analysis";

const { getBrightHubStatus, streamWorkflowExecution, updateSessionConfig } = vi.hoisted(() => ({
  getBrightHubStatus: vi.fn(),
  streamWorkflowExecution: vi.fn(),
  updateSessionConfig: vi.fn(),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, getBrightHubStatus, streamWorkflowExecution, updateSessionConfig };
});

import { useWorkspaceStore } from "../store/useWorkspaceStore";

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 94, record_count: 1000 },
  { name: "Dir_120m", height_m: 120, sensor_type: "wind_direction", data_coverage_pct: 94, record_count: 1000 },
];

const CAPABILITIES: WorkflowDispatchCapability[] = [
  { template_id: "calculate_shear_timeseries", required_params: ["height_sensors"], optional_params: [] },
  { template_id: "build_shear_table", required_params: [], optional_params: [] },
  { template_id: "extrapolate_to_hub_height", required_params: ["hub_height_m"], optional_params: [] },
  { template_id: "brighthub_prepare_reanalysis", required_params: ["latitude", "longitude"], optional_params: [] },
  { template_id: "run_ltc_linear_least_squares", required_params: ["short_col", "long_col"], optional_params: [] },
  { template_id: "run_ltc_variance_ratio", required_params: ["short_col", "long_col"], optional_params: [] },
  { template_id: "run_ensemble", required_params: ["measured_col"], optional_params: [] },
  { template_id: "run_clipping_analysis", required_params: ["speed_col"], optional_params: [] },
];

describe("prepareDefaultWorkflow", () => {
  beforeEach(() => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    const plannedConfig = buildDefaultWorkflowConfig(config, SENSORS);
    updateSessionConfig.mockReset();
    streamWorkflowExecution.mockReset();
    getBrightHubStatus.mockReset();
    updateSessionConfig.mockResolvedValue({ runconfig: serializeConfigToRunconfig(plannedConfig) });
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      summary: { timeseries_loaded: true } as never,
      serverRunconfig: { hub_height_m: 150 },
      config,
      sensors: SENSORS,
      capabilities: CAPABILITIES,
      workflowNodes: [],
      workflowEdges: [],
      defaultWorkflowStatus: "idle",
      activeTab: "setup",
      busyLabel: null,
    });
  });

  it("persists the generated defaults and opens an editable canvas", async () => {
    await useWorkspaceStore.getState().prepareDefaultWorkflow();

    const state = useWorkspaceStore.getState();
    expect(updateSessionConfig).toHaveBeenCalledOnce();
    expect(state.config.ltc.algorithms).toEqual(["linear_least_squares", "variance_ratio"]);
    expect(state.workflowNodes.map((node) => node.id)).toEqual(
      expect.arrayContaining(["ltc_linear_least_squares", "ltc_variance_ratio", "ensemble"]),
    );
    expect(state.activeTab).toBe("workflow");
    expect(state.defaultWorkflowStatus).toBe("ready");
  });

  it("asks for BrightHub credentials instead of starting an unauthenticated run", async () => {
    getBrightHubStatus.mockResolvedValue({ authenticated: false, has_token: false });

    await useWorkspaceStore.getState().saveConfigAndRunModel();

    const state = useWorkspaceStore.getState();
    expect(state.brighthubPromptRequired).toBe(true);
    expect(state.activeTab).toBe("import");
    expect(updateSessionConfig).not.toHaveBeenCalled();
    expect(streamWorkflowExecution).not.toHaveBeenCalled();
  });

  it("saves the planned config, opens Canvas, and starts the authenticated model", async () => {
    getBrightHubStatus.mockResolvedValue({ authenticated: true, has_token: true });
    streamWorkflowExecution.mockImplementation(async (_baseUrl, _sessionId, _payload, onEvent) => {
      onEvent({ run_id: "run-1", event_type: "run_started", status: "running", timestamp: "2026-08-04T20:00:00.000Z" });
      onEvent({ run_id: "run-1", event_type: "node_finished", node_id: "dataset", status: "done", timestamp: "2026-08-04T20:00:01.000Z" });
      onEvent({ run_id: "run-1", event_type: "run_finished", status: "ok", timestamp: "2026-08-04T20:00:02.000Z" });
    });

    await useWorkspaceStore.getState().saveConfigAndRunModel();

    const state = useWorkspaceStore.getState();
    expect(updateSessionConfig).toHaveBeenCalledOnce();
    expect(streamWorkflowExecution).toHaveBeenCalledOnce();
    expect(state.activeTab).toBe("workflow");
    expect(state.workflowNodes.map((node) => node.id)).toContain("brighthub_reanalysis");
    expect(state.workflowStatus?.node_statuses.dataset).toBe("done");
  });
});