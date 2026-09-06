import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

// Mock react-plotly.js so PlotFrame doesn't render a real figure in jsdom.
vi.mock("react-plotly.js", () => ({
  default: ({ layout }: { layout?: { title?: string } }) => (
    <div data-testid="plotly-stub">{String(layout?.title ?? "")}</div>
  ),
}));

// Block real network calls from auto-fetching views (PlotFrame, ExploreView stats).
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { StageShell } from "../components/stages/StageShell";
import { DataLoadView } from "../components/stages/DataLoadView";
import { ReanalysisView } from "../components/stages/ReanalysisView";
import { ExploreView } from "../components/stages/ExploreView";
import { ShearExtrapolationView } from "../components/stages/ShearExtrapolationView";
import { ReanalysisExtrapolationView } from "../components/stages/ReanalysisExtrapolationView";
import { findNearestDirectionSensor, ProfileSection, SensorReviewView } from "../components/SensorReviewView";
import { computeStageStatuses } from "../lib/stages";
import type { SensorRow, StageId, StageStatus } from "../types/analysis";

function seedStore(overrides: Partial<ReturnType<typeof useWorkspaceStore.getState>> = {}) {
  useWorkspaceStore.setState({
    session: { session_id: "s1", session_id_short: "s1" } as never,
    busyLabel: null,
    sensors: [],
    summary: { completed_steps: [], hub_height_m: 120, project_name: "Test" } as never,
    stageStatuses: computeStageStatuses([]) as unknown as Record<StageId, StageStatus>,
    selectedStage: "cleaning",
    config: useWorkspaceStore.getState().config,
    ...overrides,
  });
}

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 92, record_count: 980 },
  { name: "Dir_120m", height_m: 120, sensor_type: "wind_direction", data_coverage_pct: 93, record_count: 975 },
];

describe("Sensor Review direction pairing", () => {
  it("uses the closest direction sensor when the speed height has no exact match", () => {
    const direction = findNearestDirectionSensor(80, SENSORS.filter((sensor) => sensor.sensor_type === "wind_direction"));

    expect(direction?.name).toBe("Dir_120m");
  });
});

describe("Sensor Review diurnal selection", () => {
  it("allows sensors to be included or excluded with checkboxes", () => {
    render(<ProfileSection title="Temperature diurnal profile" sensors={SENSORS.slice(0, 2)} />);

    const firstSensor = screen.getByRole("checkbox", { name: /Spd_80m/i });
    const secondSensor = screen.getByRole("checkbox", { name: /Spd_120m/i });
    expect(firstSensor).toBeChecked();
    expect(secondSensor).toBeChecked();

    fireEvent.click(firstSensor);
    expect(firstSensor).not.toBeChecked();
    expect(secondSensor).toBeChecked();
  });
});

describe("Sensor Overview", () => {
  beforeEach(() => seedStore({ sensors: SENSORS }));

  it("shows the measurement summary and can switch to coverage analysis", () => {
    render(<SensorReviewView />);

    expect(screen.getByRole("heading", { name: "Sensor overview" })).toBeInTheDocument();
    expect(screen.getByText("Measurement inventory")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Coverage & gaps" }));
    expect(screen.getByRole("heading", { name: /Availability/i })).toBeInTheDocument();
    expect(screen.getByText("Coverage timeline")).toBeInTheDocument();
  });

  it("renders the bankable summary table and print command", () => {
    render(<SensorReviewView />);

    expect(screen.getByText("Bankable assessment summary")).toBeInTheDocument();
    expect(screen.getByText("Key assessment statistics")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print summary" })).toBeInTheDocument();
  });

  it("renders the wind-climate distribution and directional analyses", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Wind climate" }));
    expect(screen.getByText("Speed distribution & exceedance")).toBeInTheDocument();
    expect(screen.getByText("Exceedance probability")).toBeInTheDocument();
    expect(screen.getByText("Wind rose")).toBeInTheDocument();
  });

  it("renders vertical alpha and veer analysis for multi-height sensor inventories", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Vertical structure" }));
    expect(screen.getByText("Measured shear profile")).toBeInTheDocument();
    expect(screen.getByText("Wind shear alpha")).toBeInTheDocument();
    expect(screen.getByText("Wind veer")).toBeInTheDocument();
  });

  it("shows the turbulence analysis state", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Turbulence" }));
    expect(screen.getByText("Turbulence intensity")).toBeInTheDocument();
  });

  it("renders the P4 climatology and atmospheric availability surfaces", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Climatology" }));
    expect(screen.getByText("Seasonal wind-speed profile")).toBeInTheDocument();
    expect(screen.getByText("Diurnal & monthly wind-speed distributions")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Atmosphere" }));
    expect(screen.getByText("Air density")).toBeInTheDocument();
    expect(screen.getByText("Rainfall & icing")).toBeInTheDocument();
  });

  it("renders the P5 energy and advanced-analysis states", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Energy metrics" }));
    expect(screen.getByRole("heading", { name: "Energy metrics" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Advanced checks" }));
    expect(screen.getByRole("heading", { name: "Advanced checks" })).toBeInTheDocument();
  });

  it("renders the P6 comparison and MCP readiness states", () => {
    render(<SensorReviewView />);

    fireEvent.click(screen.getByRole("button", { name: "Comparison & QC" }));
    expect(screen.getByRole("heading", { name: "Comparison & QC" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "MCP readiness" }));
    expect(screen.getByRole("heading", { name: "MCP readiness" })).toBeInTheDocument();
  });
});

describe("StageShell routing", () => {
  beforeEach(() => seedStore());

  it("renders the ReanalysisView for the reanalysis stage", () => {
    useWorkspaceStore.setState({ selectedStage: "reanalysis" });
    render(<StageShell />);
    expect(screen.getByText("Acquisition settings")).toBeInTheDocument();
    expect(screen.getByText("BrightHub reanalysis nodes")).toBeInTheDocument();
  });

  it("renders the ExploreView for the explore stage", () => {
    useWorkspaceStore.setState({ selectedStage: "explore", sensors: SENSORS });
    render(<StageShell />);
    expect(screen.getByText("Sensor selection")).toBeInTheDocument();
  });

  it("renders the ShearExtrapolationView for the shear stage", () => {
    useWorkspaceStore.setState({ selectedStage: "shear", sensors: SENSORS });
    render(<StageShell />);
    expect(screen.getByText("Method & sensors")).toBeInTheDocument();
  });

  it("renders the ReanalysisExtrapolationView for reanalysis_extrapolation", () => {
    useWorkspaceStore.setState({ selectedStage: "reanalysis_extrapolation" });
    render(<StageShell />);
    expect(screen.getByText("Reanalysis → hub confirmation")).toBeInTheDocument();
  });

  it("renders the LtcView for the ltc stage (Phase E)", () => {
    useWorkspaceStore.setState({ selectedStage: "ltc" });
    render(<StageShell />);
    expect(screen.getByText("Columns")).toBeInTheDocument();
    expect(screen.getByText("Algorithms")).toBeInTheDocument();
  });
});

describe("DataLoadView", () => {
  beforeEach(() => seedStore({ sensors: SENSORS }));

  it("renders the sensor inventory when sensors are loaded", () => {
    render(<DataLoadView />);
    expect(screen.getByText("Analysis sensor selection")).toBeInTheDocument();
    expect(screen.getByText("Spd_80m")).toBeInTheDocument();
    expect(screen.getByText("Spd_120m")).toBeInTheDocument();
  });

  it("removes excluded sensors when saving config with apply-selection checked", async () => {
    const deleteSensors = vi.fn(async () => {});
    const saveConfigAndSetup = vi.fn(async () => {});
    useWorkspaceStore.setState({ deleteSensors, saveConfigAndSetup });
    render(<DataLoadView />);

    // Uncheck Spd_80m to exclude it
    const speedSensor = screen.getByRole("checkbox", { name: "Include Spd_80m" });
    fireEvent.click(speedSensor);

    // The "Apply sensor selection" checkbox should appear (checked by default)
    const applyCheck = screen.getByRole("checkbox", { name: /apply sensor selection/i });
    expect(applyCheck).toBeChecked();

    // Click "Save config and setup" — should apply selection then save
    const saveButton = screen.getByRole("button", { name: /save config and setup/i });
    await act(async () => {
      fireEvent.click(saveButton);
    });

    expect(deleteSensors).toHaveBeenCalledWith(["Spd_80m"]);
  });

  it("selects and clears all imported sensors from the top checkbox", () => {
    render(<DataLoadView />);

    const selectAll = screen.getByRole("checkbox", { name: "Select all sensors" });
    expect(selectAll).toBeChecked();

    fireEvent.click(selectAll);
    expect(screen.getByRole("checkbox", { name: "Include Spd_80m" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Include Spd_120m" })).not.toBeChecked();

    fireEvent.click(selectAll);
    expect(screen.getByRole("checkbox", { name: "Include Spd_80m" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Include Spd_120m" })).toBeChecked();
  });

  it("renders the site & hub config form", () => {
    render(<DataLoadView />);
    expect(screen.getByText("Site & hub height")).toBeInTheDocument();
    expect(screen.getByLabelText("Hub height (m)")).toHaveValue(null);
    expect(screen.getByRole("button", { name: "Save config and setup" })).toBeInTheDocument();
  });
});

describe("ReanalysisView", () => {
  beforeEach(() => seedStore());

  it("warns to connect BrightHub when unauthenticated", () => {
    useWorkspaceStore.setState({ brighthubStatus: { authenticated: false, has_token: false } } as never);
    render(<ReanalysisView />);
    expect(screen.getByText("BrightHub reanalysis nodes")).toBeInTheDocument();
  });

  it("shows node tables once reanalysis nodes are loaded", () => {
    useWorkspaceStore.setState({
      brighthubStatus: { authenticated: true, has_token: true } as never,
      brighthubReanalysis: {
        era5_nodes: [{ latitude_ddeg: 52.4, longitude_ddeg: 4.9, distance_km: 5, bearing: "N" }],
        merra2_nodes: [],
      } as never,
      era5Nodes: [{ latitude: 52.4, longitude: 4.9, distance_km: 5, bearing: "N" }],
      merraNodes: [],
    });
    const { container } = render(<ReanalysisView />);
    expect(container.querySelector(".node-table")).toBeTruthy();
  });

  it("asks for the EarthDataHub credential before offering the direct-ERA5 actions", () => {
    const config = useWorkspaceStore.getState().config;
    useWorkspaceStore.setState({
      config: { ...config, reanalysis: { ...config.reanalysis, acquisitionSource: "earthdatahub" } },
      earthdatahubStatus: { configured: false },
    });
    render(<ReanalysisView />);
    expect(screen.getByText(/configure your earthdatahub credential/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /find era5 nodes/i })).not.toBeInTheDocument();
  });

  it("extracts every discovered node's own coordinate, not the site's, on the direct EarthDataHub path", async () => {
    // Regression: extracting only the site coordinate left every node key the interpolation
    // step looks for missing, so ERA5 (not just MERRA-2) always showed unavailable in the
    // Analysis Engine on this path. See useWorkspaceStore's runReanalysisAcquisition for the
    // same fix applied to the automatic (non-manual) acquisition flow.
    const config = useWorkspaceStore.getState().config;
    const discoveredNodes = [
      { latitude: 52.25, longitude: 4.75 },
      { latitude: 52.5, longitude: 5.0 },
    ];
    const invoke = vi.fn((...args: [string, string, string, unknown?]) => {
      if (args[0] === "Find ERA5 nodes (direct)") return Promise.resolve({ nodes: discoveredNodes });
      return Promise.resolve({});
    });
    useWorkspaceStore.setState({
      config: {
        ...config,
        site: { ...config.site, latitude: 52.4, longitude: 4.9 },
        reanalysis: { ...config.reanalysis, acquisitionSource: "earthdatahub" },
      },
      earthdatahubStatus: { configured: true },
      invokeSessionOperation: invoke as never,
    });
    render(<ReanalysisView />);

    const extractButton = screen.getByRole("button", { name: /extract node data/i });
    expect(extractButton).toBeDisabled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /find era5 nodes/i }));
    });
    expect(extractButton).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(extractButton);
    });

    const extractCalls = invoke.mock.calls.filter((call) => call[0] === "Extract ERA5 (direct)");
    expect(extractCalls).toHaveLength(2);
    expect(extractCalls.map((call) => (call[3] as { latitude: number }).latitude)).toEqual([52.25, 52.5]);
    expect(extractCalls.every((call) => (call[3] as { latitude: number }).latitude !== 52.4)).toBe(true);
  });

  it("reports per-node progress in the store while extracting via the direct EarthDataHub path", async () => {
    const config = useWorkspaceStore.getState().config;
    const discoveredNodes = [
      { latitude: 52.25, longitude: 4.75 },
      { latitude: 52.5, longitude: 5.0 },
    ];
    let settleFirstExtract: (() => void) | undefined;
    const invoke = vi.fn((...args: [string, string, string, unknown?]) => {
      if (args[0] === "Find ERA5 nodes (direct)") return Promise.resolve({ nodes: discoveredNodes });
      if (args[0] === "Extract ERA5 (direct)" && !settleFirstExtract) {
        return new Promise((resolve) => {
          settleFirstExtract = () => resolve({});
        });
      }
      return Promise.resolve({});
    });
    useWorkspaceStore.setState({
      config: {
        ...config,
        site: { ...config.site, latitude: 52.4, longitude: 4.9 },
        reanalysis: { ...config.reanalysis, acquisitionSource: "earthdatahub" },
      },
      earthdatahubStatus: { configured: true },
      invokeSessionOperation: invoke as never,
    });
    render(<ReanalysisView />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /find era5 nodes/i }));
    });

    const extractPromise = act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /extract node data/i }));
    });

    // Flush microtasks enough to reach the still-pending first extract call.
    for (let i = 0; i < 10; i += 1) {
      await Promise.resolve();
    }
    expect(useWorkspaceStore.getState().reanalysisProgress).toMatchObject({
      provider: "earthdatahub",
      phase: "downloading",
      current: 1,
      total: 2,
      latitude: 52.25,
      longitude: 4.75,
    });

    settleFirstExtract?.();
    await extractPromise;

    // Cleared once the whole loop settles, not left dangling on the last node.
    expect(useWorkspaceStore.getState().reanalysisProgress).toBeNull();
  });
});

describe("ExploreView", () => {
  beforeEach(() => seedStore({ sensors: SENSORS }));

  it("renders the sensor pickers and plot cells", () => {
    render(<ExploreView />);
    // Speed-sensor-gated panels always render when a speed sensor is seeded.
    expect(screen.getByText("Coverage timeline")).toBeInTheDocument();
    expect(screen.getByText("Weibull fit")).toBeInTheDocument();
    // Wind rose is gated on a direction sensor; with none selected it shows the
    // "select the required sensor" hint instead of the title.
    expect(screen.getByText(/select the required sensor/i)).toBeInTheDocument();
  });
});

describe("ShearExtrapolationView", () => {
  beforeEach(() => seedStore({ sensors: SENSORS }));

  it("disables compute until ≥2 sensors chosen", () => {
    render(<ShearExtrapolationView />);
    const button = screen.getByRole("button", { name: /compute/i });
    expect(button).toBeDisabled();
  });
});

describe("ReanalysisExtrapolationView", () => {
  beforeEach(() => seedStore());

  it("reports the reference column at the configured hub height", () => {
    render(<ReanalysisExtrapolationView />);
    expect(screen.getByText("Spd_0m_hub")).toBeInTheDocument();
  });
});
