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
  downloadBrightHubReanalysis,
  getEarthDataHubStatus,
  setEarthDataHubCredential,
  clearEarthDataHubCredential,
} = vi.hoisted(() => ({
  getBrightHubStatus: vi.fn(),
  streamWorkflowExecution: vi.fn(),
  updateSessionConfig: vi.fn(),
  fetchBrightHubReanalysisNodes: vi.fn(),
  downloadBrightHubReanalysis: vi.fn(),
  getEarthDataHubStatus: vi.fn(),
  setEarthDataHubCredential: vi.fn(),
  clearEarthDataHubCredential: vi.fn(),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    getBrightHubStatus,
    streamWorkflowExecution,
    updateSessionConfig,
    fetchBrightHubReanalysisNodes,
    downloadBrightHubReanalysis,
    getEarthDataHubStatus,
    setEarthDataHubCredential,
    clearEarthDataHubCredential,
  };
});

import { useWorkspaceStore } from "../store/useWorkspaceStore";

// Captured before any test can overwrite it: the "runReanalysisAcquisition" tests replace
// this store action wholesale with a stub, and nothing restores it afterwards - the
// "downloadBrightHubReanalysis" describe block below re-installs this real implementation
// so it is actually exercising the action under test, not a leftover stub.
const REAL_DOWNLOAD_BRIGHTHUB_REANALYSIS = useWorkspaceStore.getState().downloadBrightHubReanalysis;

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

  it("asks for an EarthDataHub credential instead of running acquisition unauthenticated", async () => {
    // Regression: unlike the BrightHub gate above, there was no equivalent check for the
    // direct-ERA5 (EarthDataHub) path - a missing/cleared PAT let the flow run straight into
    // `runReanalysisAcquisition`, which failed deep inside "Find ERA5 nodes (direct)" with an
    // opaque 401, then silently moved on to Cleaning with ERA5 never interpolated.
    getEarthDataHubStatus.mockResolvedValue({ configured: false });
    useWorkspaceStore.setState((state) => ({
      config: { ...state.config, reanalysis: { ...state.config.reanalysis, acquisitionSource: "earthdatahub" } },
    }));

    await useWorkspaceStore.getState().saveConfigAndSetup();

    const state = useWorkspaceStore.getState();
    expect(state.activeTab).toBe("import");
    expect(updateSessionConfig).not.toHaveBeenCalled();
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

describe("runReanalysisAcquisition", () => {
  it("interpolates MERRA-2 as well as ERA5 once both BrightHub downloads succeed", async () => {
    // Regression: `/era5/interpolate` defaults to `source: "era5"`, and this action called
    // it exactly once. MERRA-2 was downloaded (the two `downloadBrightHubReanalysis` calls
    // below) but never interpolated, so `state.reanalysis_interpolated["merra2"]` never got
    // populated and MERRA-2 stayed permanently unavailable in the Analysis Engine despite
    // being fully downloaded — the Canvas's own reanalysis node avoids this only because it
    // calls a different backend tool (`brighthub_prepare_reanalysis`) that interpolates both.
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    const fetchNodes = vi.fn(async () => {
      useWorkspaceStore.setState({ brighthubReanalysis: {} as never });
    });
    const download = vi.fn(async () => {});
    const invoke = vi.fn((..._args: [string, string, string, unknown?]) => Promise.resolve({}));
    useWorkspaceStore.setState({
      config,
      fetchBrightHubReanalysisNodes: fetchNodes,
      downloadBrightHubReanalysis: download,
      invokeSessionOperation: invoke as never,
      brighthubReanalysis: null,
    });

    await useWorkspaceStore.getState().runReanalysisAcquisition();

    expect(download).toHaveBeenCalledWith({ dataset: "ERA5", source: "brighthub", useNodes: "era5" });
    expect(download).toHaveBeenCalledWith({ dataset: "MERRA-2", source: "brighthub", useNodes: "merra2" });
    expect(invoke).toHaveBeenCalledWith("Interpolate ERA5 to site", "POST", "/era5/interpolate");
    expect(invoke).toHaveBeenCalledWith("Interpolate MERRA-2 to site", "POST", "/era5/interpolate", {
      source: "merra2",
    });
  });

  it("does not request a MERRA-2 interpolation on the direct EarthDataHub path, which never downloads it", async () => {
    const config = createDefaultWindAnalysisConfig();
    config.reanalysis.acquisitionSource = "earthdatahub";
    const invoke = vi.fn((..._args: [string, string, string, unknown?]) => Promise.resolve({}));
    useWorkspaceStore.setState({ config, invokeSessionOperation: invoke as never });

    await useWorkspaceStore.getState().runReanalysisAcquisition();

    for (const call of invoke.mock.calls) {
      expect(call[3]).not.toEqual({ source: "merra2" });
    }
  });

  it("extracts each discovered node's own coordinate, not just the site's, on the direct EarthDataHub path", async () => {
    // Regression: `_interpolate_era5_to_site` requires all four bounding-grid nodes' data to
    // be present in `state.era5_data`; extracting only the site's own coordinate left every
    // node key interpolation looks for missing, so it always raised and
    // `reanalysis_interpolated["era5"]` never got populated — which is what left ERA5 (not
    // just MERRA-2, which genuinely has no data on this path) showing unavailable in the
    // Analysis Engine whenever EarthDataHub was chosen.
    const config = createDefaultWindAnalysisConfig();
    config.reanalysis.acquisitionSource = "earthdatahub";
    config.site.latitude = 52.4;
    config.site.longitude = 4.8;
    const discoveredNodes = [
      { latitude: 52.25, longitude: 4.75 },
      { latitude: 52.25, longitude: 5.0 },
      { latitude: 52.5, longitude: 4.75 },
      { latitude: 52.5, longitude: 5.0 },
    ];
    const invoke = vi.fn((label: string) => {
      if (label === "Find ERA5 nodes (direct)") return Promise.resolve({ nodes: discoveredNodes });
      return Promise.resolve({});
    });
    useWorkspaceStore.setState({ config, invokeSessionOperation: invoke as never });

    await useWorkspaceStore.getState().runReanalysisAcquisition();

    const extractCalls = invoke.mock.calls.filter((call) => call[0] === "Extract ERA5 (direct)");
    expect(extractCalls).toHaveLength(discoveredNodes.length);
    for (const node of discoveredNodes) {
      expect(extractCalls).toContainEqual([
        "Extract ERA5 (direct)",
        "POST",
        "/era5/extract",
        {
          latitude: node.latitude,
          longitude: node.longitude,
          start_date: config.reanalysis.startDate,
          end_date: config.reanalysis.endDate,
        },
      ]);
    }
    // Never the bare site coordinate, which is the bug this replaces.
    expect(extractCalls).not.toContainEqual(
      expect.arrayContaining([expect.objectContaining({ latitude: 52.4, longitude: 4.8 })]),
    );
  });
});

describe("downloadBrightHubReanalysis", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ downloadBrightHubReanalysis: REAL_DOWNLOAD_BRIGHTHUB_REANALYSIS });
  });

  it("downloads one node per request instead of one bulk request, reporting progress for each", async () => {
    // Regression: the action used to send every node in a single request, so there was no
    // per-node signal to drive the blocking progress overlay ("node X of Y", coordinates).
    // The endpoint accepts a node list of any size, so looping one-at-a-time gives real
    // progress at the cost of one extra round-trip per node.
    downloadBrightHubReanalysis.mockReset();
    downloadBrightHubReanalysis.mockImplementation(
      async (_baseUrl: string, _sessionId: string, payload: { dataset: string; nodes: Array<{ latitude_ddeg: number; longitude_ddeg: number }> }) => ({
        dataset: payload.dataset,
        source: "brighthub",
        items: payload.nodes.map((n) => ({ latitude: n.latitude_ddeg, longitude: n.longitude_ddeg, rows: 10 })),
      }),
    );
    const nodes = [
      { latitude_ddeg: 52.25, longitude_ddeg: 4.75, distance_km: 5 },
      { latitude_ddeg: 52.5, longitude_ddeg: 5.0, distance_km: 8 },
    ];
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      brighthubReanalysis: { era5_nodes: nodes, merra2_nodes: [] } as never,
    });

    await useWorkspaceStore
      .getState()
      .downloadBrightHubReanalysis({ dataset: "ERA5", source: "brighthub", useNodes: "era5" });

    expect(downloadBrightHubReanalysis).toHaveBeenCalledTimes(2);
    expect(downloadBrightHubReanalysis).toHaveBeenNthCalledWith(1, expect.anything(), "session-1", {
      dataset: "ERA5",
      source: "brighthub",
      nodes: [nodes[0]],
    });
    expect(downloadBrightHubReanalysis).toHaveBeenNthCalledWith(2, expect.anything(), "session-1", {
      dataset: "ERA5",
      source: "brighthub",
      nodes: [nodes[1]],
    });
    // Cleared once the whole download settles, not left dangling on the last node.
    expect(useWorkspaceStore.getState().reanalysisProgress).toBeNull();
  });

  it("exposes the current node index and coordinate mid-download", async () => {
    downloadBrightHubReanalysis.mockReset();
    let settleFirst: (() => void) | undefined;
    downloadBrightHubReanalysis.mockImplementation(
      async (_baseUrl: string, _sessionId: string, payload: { dataset: string; nodes: Array<{ latitude_ddeg: number; longitude_ddeg: number }> }) => {
        if (!settleFirst) {
          return new Promise((resolve) => {
            settleFirst = () =>
              resolve({
                dataset: payload.dataset,
                source: "brighthub",
                items: payload.nodes.map((n) => ({ latitude: n.latitude_ddeg, longitude: n.longitude_ddeg })),
              });
          });
        }
        return {
          dataset: payload.dataset,
          source: "brighthub",
          items: payload.nodes.map((n) => ({ latitude: n.latitude_ddeg, longitude: n.longitude_ddeg })),
        };
      },
    );
    const nodes = [
      { latitude_ddeg: 52.25, longitude_ddeg: 4.75, distance_km: 5 },
      { latitude_ddeg: 52.5, longitude_ddeg: 5.0, distance_km: 8 },
    ];
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      brighthubReanalysis: { era5_nodes: nodes, merra2_nodes: [] } as never,
    });

    const downloadPromise = useWorkspaceStore
      .getState()
      .downloadBrightHubReanalysis({ dataset: "ERA5", source: "brighthub", useNodes: "era5" });

    for (let i = 0; i < 10; i += 1) {
      await Promise.resolve();
    }
    expect(useWorkspaceStore.getState().reanalysisProgress).toMatchObject({
      provider: "brighthub",
      phase: "downloading",
      dataset: "ERA5",
      current: 1,
      total: 2,
      latitude: 52.25,
      longitude: 4.75,
      distanceKm: 5,
    });

    settleFirst?.();
    await downloadPromise;
    expect(useWorkspaceStore.getState().reanalysisProgress).toBeNull();
  });
});

describe("EarthDataHub credential (session-scoped, not an env file)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      earthdatahubStatus: null,
    });
  });

  it("refreshes status from the backend", async () => {
    getEarthDataHubStatus.mockResolvedValue({ configured: true });

    await useWorkspaceStore.getState().refreshEarthDataHub();

    expect(getEarthDataHubStatus).toHaveBeenCalledWith(expect.anything(), "session-1");
    expect(useWorkspaceStore.getState().earthdatahubStatus).toEqual({ configured: true });
  });

  it("degrades to unconfigured rather than throwing when the status check fails", async () => {
    getEarthDataHubStatus.mockRejectedValue(new Error("network error"));

    await useWorkspaceStore.getState().refreshEarthDataHub();

    expect(useWorkspaceStore.getState().earthdatahubStatus).toEqual({ configured: false });
  });

  it("saves a credential and reflects it as configured", async () => {
    setEarthDataHubCredential.mockResolvedValue({ status: "ok", configured: true });

    await useWorkspaceStore.getState().setEarthDataHubCredential("my-pat");

    expect(setEarthDataHubCredential).toHaveBeenCalledWith(expect.anything(), "session-1", "my-pat");
    expect(useWorkspaceStore.getState().earthdatahubStatus).toEqual({ configured: true });
  });

  it("clears a credential and reflects it as unconfigured", async () => {
    useWorkspaceStore.setState({ earthdatahubStatus: { configured: true } });
    clearEarthDataHubCredential.mockResolvedValue({ status: "ok", configured: false });

    await useWorkspaceStore.getState().clearEarthDataHubCredential();

    expect(clearEarthDataHubCredential).toHaveBeenCalledWith(expect.anything(), "session-1");
    expect(useWorkspaceStore.getState().earthdatahubStatus).toEqual({ configured: false });
  });

  it("reports a save failure in the activity log without leaving a stale busy label", async () => {
    setEarthDataHubCredential.mockRejectedValue(new Error("bad pat"));

    await useWorkspaceStore.getState().setEarthDataHubCredential("bad");

    const state = useWorkspaceStore.getState();
    expect(state.busyLabel).toBeNull();
    expect(state.activity[0]?.label).toBe("EarthDataHub credential failed");
  });
});