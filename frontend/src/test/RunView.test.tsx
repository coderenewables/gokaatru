// Run phase (design doc: Run) — SweepDesigner and SweepMonitor on one screen instead of
// two sub-tabs. No ETA figure ships here: estimateSweep only ever returns leaf/prefix
// counts, and the mockup's ETA formula has no basis in this codebase (see plan Step 4).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const getSweepAxes = vi.fn();
const estimateSweep = vi.fn();

vi.mock("../lib/sweepApi", () => ({
  getSweepAxes: (...args: unknown[]) => getSweepAxes(...args),
  estimateSweep: (...args: unknown[]) => estimateSweep(...args),
  getPrefixHash: vi.fn(),
  runSweep: vi.fn(),
  streamSweep: vi.fn(),
  listSweeps: vi.fn().mockResolvedValue([]),
  getSweep: vi.fn(),
  getScenarioRunconfig: vi.fn(),
}));

import { RunView } from "../components/RunView";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { useSweepStore } from "../store/useSweepStore";

beforeEach(() => {
  vi.clearAllMocks();
  getSweepAxes.mockResolvedValue({
    sensor_policies: [{ name: "nearest_2", available: true, resolved_columns: ["Spd_100m"] }],
    shear_models: [{ name: "power_law_mean", available: true }],
    reference_sources: [{ name: "era5", available: true }],
    power_curves: ["generic-3.0MW-130m-IIA"],
    known_sensor_policies: ["nearest_2"],
    default_thresholds: {},
  });
  estimateSweep.mockResolvedValue({ leaf_count: 12, prefix_count: 3, spec: {} });
  useWorkspaceStore.setState({ session: { session_id: "s1" } as never });
  useSweepStore.setState({
    phase: "idle",
    axes: null,
    axesError: null,
    droppedLevels: [],
    rows: [],
    manifest: null,
    sweeps: [],
    progress: { completed: 0, total: 0 },
    events: [],
  });
});

describe("RunView", () => {
  it("shows the sweep designer and no monitor while idle", async () => {
    render(<RunView />);
    expect(await screen.findByRole("button", { name: "Run sweep" })).toBeInTheDocument();
    expect(screen.queryByText(/leaves completed|run complete/i)).toBeNull();
  });

  it("shows the monitor once the run has started, alongside the designer", async () => {
    useSweepStore.setState({ phase: "running" });
    render(<RunView />);
    // The designer's own Run button is still on screen, now reading "Running…".
    expect(await screen.findByRole("button", { name: "Running…" })).toBeInTheDocument();
    expect(screen.getAllByText(/scenarios/i).length).toBeGreaterThan(0);
  });

  it("shows the real preset names, not the mockup's 'Smoke test'", async () => {
    render(<RunView />);
    expect(await screen.findByRole("button", { name: "Quick look" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Standard EYA" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exhaustive" })).toBeInTheDocument();
    expect(screen.queryByText(/smoke test/i)).toBeNull();
  });

  it("shows no ETA figure anywhere, idle or running", async () => {
    render(<RunView />);
    await screen.findByRole("button", { name: "Run sweep" });
    expect(screen.queryByText(/\bETA\b|estimated (wall clock|time)/i)).toBeNull();
  });
});
