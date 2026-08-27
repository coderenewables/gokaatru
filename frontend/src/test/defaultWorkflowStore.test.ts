import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDefaultWorkflowConfig } from "../lib/defaultWorkflowPlan";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { serializeConfigToRunconfig } from "../lib/configSync";
import type { SensorRow, WorkflowDispatchCapability } from "../types/analysis";

const {
  getBrightHubStatus,
  streamWorkflowExecution,
  updateSessionConfig,
  fetchBrightHubReanalysisNodes,
} = vi.hoisted(() => ({
  getBrightHubStatus: vi.fn(),
  streamWorkflowExecution: vi.fn(),
  updateSessionConfig: vi.fn(),
  fetchBrightHubReanalysisNodes: vi.fn(),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    getBrightHubStatus,
    streamWorkflowExecution,
    updateSessionConfig,
    fetchBrightHubReanalysisNodes,
  };
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
    fetchBrightHubReanalysisNodes.mockReset();
    fetchBrightHubReanalysisNodes.mockRejectedValue(new Error("offline in tests"));
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
      brighthubReanalysis: null,
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

  it("asks for BrightHub credentials instead of downloading unauthenticated", async () => {
    getBrightHubStatus.mockResolvedValue({ authenticated: false, has_token: false });

    await useWorkspaceStore.getState().saveConfigAndSetup();

    const state = useWorkspaceStore.getState();
    expect(state.brighthubPromptRequired).toBe(true);
    expect(state.activeTab).toBe("import");
    expect(updateSessionConfig).not.toHaveBeenCalled();
    expect(fetchBrightHubReanalysisNodes).not.toHaveBeenCalled();
  });

  it("saves the planned config and starts reanalysis acquisition without running Canvas", async () => {
    getBrightHubStatus.mockResolvedValue({ authenticated: true, has_token: true });

    await useWorkspaceStore.getState().saveConfigAndSetup();

    const state = useWorkspaceStore.getState();
    expect(updateSessionConfig).toHaveBeenCalledOnce();
    expect(fetchBrightHubReanalysisNodes).toHaveBeenCalledOnce();
    expect(streamWorkflowExecution).not.toHaveBeenCalled();
    expect(state.activeTab).toBe("cleaning");
    expect(state.defaultWorkflowStatus).toBe("ready");
    expect(state.workflowNodes.map((node) => node.id)).toContain("brighthub_reanalysis");
  });

  it("stays on Import with a reanalysis spinner until the download settles, then moves to Cleaning", async () => {
    // Regression: activeTab used to jump to "cleaning" (and busyLabel to null) before the
    // reanalysis download was even requested, so the download's own progress labels flashed
    // in on a page that had already moved on. The transition to Cleaning must wait for
    // acquisition to finish, not race ahead of it.
    getBrightHubStatus.mockResolvedValue({ authenticated: true, has_token: true });
    let settleNodesFetch: (() => void) | undefined;
    fetchBrightHubReanalysisNodes.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          settleNodesFetch = () => reject(new Error("offline in tests"));
        }),
    );

    const setupPromise = useWorkspaceStore.getState().saveConfigAndSetup();

    // Flush the microtask queue enough to carry the action through its own chained awaits
    // (getBrightHubStatus, updateSessionConfig) up to the still-pending reanalysis fetch,
    // without any real timer — every other call in this test resolves synchronously.
    for (let i = 0; i < 20; i += 1) {
      await Promise.resolve();
    }

    const midFlight = useWorkspaceStore.getState();
    expect(midFlight.activeTab).not.toBe("cleaning");
    expect(midFlight.busyLabel).toBeTruthy();
    expect(midFlight.busyLabel).toMatch(/reanalysis/i);

    settleNodesFetch?.();
    await setupPromise;

    const settled = useWorkspaceStore.getState();
    expect(settled.activeTab).toBe("cleaning");
    expect(settled.busyLabel).toBeNull();
  });
});