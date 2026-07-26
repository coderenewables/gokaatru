import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

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
import { computeStageStatuses } from "../lib/stages";
import type { SensorRow, StageId, StageStatus } from "../types/analysis";

function seedStore(overrides: Partial<ReturnType<typeof useWorkspaceStore.getState>> = {}) {
  useWorkspaceStore.setState({
    session: { session_id: "s1", session_id_short: "s1" } as never,
    busyLabel: null,
    sensors: [],
    summary: { completed_steps: [], hub_height_m: 120, project_name: "Test" } as never,
    stageStatuses: computeStageStatuses([]) as unknown as Record<StageId, StageStatus>,
    selectedStage: "data",
    config: useWorkspaceStore.getState().config,
    ...overrides,
  });
}

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 92, record_count: 980 },
  { name: "Dir_120m", height_m: 120, sensor_type: "wind_direction", data_coverage_pct: 93, record_count: 975 },
];

describe("StageShell routing", () => {
  beforeEach(() => seedStore());

  it("renders the DataLoadView for the data stage", () => {
    useWorkspaceStore.setState({ selectedStage: "data" });
    render(<StageShell />);
    // The three path tabs render (use role to avoid clashing with panel headings).
    expect(screen.getByRole("tab", { name: "Upload files" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "BrightHub import" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Shared dataset" })).toBeInTheDocument();
  });

  it("renders the ReanalysisView for the reanalysis stage", () => {
    useWorkspaceStore.setState({ selectedStage: "reanalysis" });
    render(<StageShell />);
    expect(screen.getByText("Site coordinate")).toBeInTheDocument();
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
    expect(screen.getByText("Sensor inventory")).toBeInTheDocument();
    expect(screen.getByText("Spd_80m")).toBeInTheDocument();
    expect(screen.getByText("Spd_120m")).toBeInTheDocument();
  });

  it("renders the site & hub config form", () => {
    render(<DataLoadView />);
    expect(screen.getByText("Site & hub height")).toBeInTheDocument();
    expect(screen.getByLabelText("Hub height (m)")).toBeInTheDocument();
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
    // config default hub height is 120
    expect(screen.getByText("Spd_120m_hub")).toBeInTheDocument();
  });
});
