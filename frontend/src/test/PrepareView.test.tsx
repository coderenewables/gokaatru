// Prepare phase (design doc: Prepare) — merges Data import / Data cleaning / Reanalysis /
// Sensor Overview / Stepper into one screen with an internal section switcher, ending in
// the stamped prefix hash. Composes DataLoadView / StageShell / SensorReviewView unchanged.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("react-plotly.js", () => ({
  default: ({ layout }: { layout?: { title?: string } }) => (
    <div data-testid="plotly-stub">{String(layout?.title ?? "")}</div>
  ),
}));

vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { PrepareView } from "../components/PrepareView";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { computeStageStatuses } from "../lib/stages";
import type { SensorRow, StageId, StageStatus } from "../types/analysis";

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 90, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 100, record_count: 1000 },
];

function seedStore(overrides: Partial<ReturnType<typeof useWorkspaceStore.getState>> = {}) {
  useWorkspaceStore.setState({
    session: { session_id: "s1", session_id_short: "s1" } as never,
    busyLabel: null,
    sensors: SENSORS,
    summary: { completed_steps: [], hub_height_m: 120, project_name: "Test" } as never,
    stageStatuses: computeStageStatuses([]) as unknown as Record<StageId, StageStatus>,
    selectedStage: "cleaning",
    prepareSection: "data",
    prefixHash: null,
    reanalysisSourcesForPrefix: [],
    cleaningActionsCount: 0,
    config: useWorkspaceStore.getState().config,
    loadPrefixHash: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  });
}

describe("PrepareView", () => {
  beforeEach(() => seedStore());

  it("shows the intro and the Data loading section by default", () => {
    render(<PrepareView />);
    expect(screen.getByText("Everything the scenarios will share")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save config and setup" })).toBeInTheDocument();
    expect(screen.queryByText("Data cleaning is optional")).toBeNull();
    expect(screen.queryByText("Sensor overview")).toBeNull();
  });

  it("fetches the prefix hash on mount", () => {
    render(<PrepareView />);
    expect(useWorkspaceStore.getState().loadPrefixHash).toHaveBeenCalled();
  });

  it("switches to the Pipeline section and shows the stage content", () => {
    render(<PrepareView />);
    fireEvent.click(screen.getByRole("button", { name: "Pipeline" }));
    expect(useWorkspaceStore.getState().prepareSection).toBe("pipeline");
    expect(screen.getByText("Data cleaning is optional")).toBeInTheDocument();
  });

  it("switches to the Sensor Overview section", () => {
    render(<PrepareView />);
    fireEvent.click(screen.getByRole("button", { name: "Sensor Overview" }));
    expect(useWorkspaceStore.getState().prepareSection).toBe("sensors");
    expect(screen.getByText("Sensor overview")).toBeInTheDocument();
  });

  it("computes the data-recovery tile from real sensor coverage, not a placeholder", () => {
    render(<PrepareView />);
    // mean of 90 and 100 = 95.0
    expect(screen.getByText("95.0%")).toBeInTheDocument();
  });

  it("shows no stamp banner until the prefix hash has loaded", () => {
    render(<PrepareView />);
    expect(screen.queryByText(/Prefix stamped/)).toBeNull();
  });

  it("shows the stamp banner once the prefix hash is set, and its CTA moves to Run", () => {
    seedStore({ prefixHash: "a3f19c2b1e0d4f77", reanalysisSourcesForPrefix: ["era5"], cleaningActionsCount: 2 });
    render(<PrepareView />);
    expect(screen.getByText(/Prefix stamped · a3f19c2b1e0d4f77/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Design the sweep" }));
    expect(useWorkspaceStore.getState().activePhase).toBe("run");
  });
});
