// Canvas absorbs Compare (design doc: Interrogate/Compare retirement) — CompareView's
// run-comparison capability is retired as a top-level tab and relocated behind a toggle
// inside the Canvas view, since it operates on saved workflow runs (Canvas's own data),
// not sweep scenarios.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

// React Flow needs a ResizeObserver, which jsdom does not provide.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// Block real network calls from the store's mount-time refreshes.
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { WorkflowView } from "../components/WorkflowView";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { useSweepStore } from "../store/useSweepStore";
import type { WorkflowRunSummary } from "../lib/api";
import type { SweepManifestScenario, SweepSummary } from "../types/sweep";

const RUNS: WorkflowRunSummary[] = [
  { run_id: "run-aaaaaaaa", status: "completed", started_at: "2026-09-01T00:00:00Z", finished_at: "2026-09-01T00:05:00Z", node_count: 5, completed_node_count: 5 },
  { run_id: "run-bbbbbbbb", status: "completed", started_at: "2026-09-02T00:00:00Z", finished_at: "2026-09-02T00:05:00Z", node_count: 5, completed_node_count: 4 },
];

const SWEEPS: SweepSummary[] = [
  {
    sweep_id: "sweep-1",
    started_at: "2026-09-01T00:00:00Z",
    finished_at: "2026-09-01T00:10:00Z",
    counts: { planned: 8, run: 8, completed: 8, admissible: 6, excluded: 2, failed: 0 } as never,
    fixed_prefix_hash: "a3f19c2b1e0d4f77",
  },
];

const SCENARIOS: SweepManifestScenario[] = [
  {
    config_hash: "c1a2b3c4",
    status: "ok",
    admissible: true,
    runconfig: "sweep-1/c1a2b3c4/runconfig.json",
    shear_fit_policy: "nearest_2",
    shear_model: "power_law_mean",
    reference_source: "era5",
    ltc_algorithm: "variance_ratio",
  },
  {
    config_hash: "d5e6f7a8",
    status: "ok",
    admissible: false,
    runconfig: "sweep-1/d5e6f7a8/runconfig.json",
    shear_fit_policy: "widest_lever",
    shear_model: "log_law_mean",
    reference_source: "merra2",
    ltc_algorithm: "speedsort",
  },
];

beforeEach(() => {
  useWorkspaceStore.setState({
    session: { session_id: "s1" } as never,
    workflowNodes: [],
    workflowEdges: [],
    workflowStatus: null,
    workflowSnapshots: [],
    workflowRuns: RUNS,
    selectedWorkflowRunIds: [],
    workflowRunComparison: null,
    serverRunconfig: {},
    loadScenarioIntoCanvas: vi.fn().mockResolvedValue(undefined),
  });
  useSweepStore.setState({
    sweeps: SWEEPS,
    refreshSweeps: vi.fn().mockResolvedValue(undefined),
    previewSweepScenarios: vi.fn().mockResolvedValue(SCENARIOS),
  });
});

describe("Canvas — Compare runs toggle", () => {
  it("starts on the canvas, with Compare runs reachable but not shown", () => {
    render(<WorkflowView />);
    expect(screen.getByRole("button", { name: "Compare runs" })).toBeInTheDocument();
    expect(screen.queryByText("Saved workflow runs")).toBeNull();
  });

  it("shows CompareView's content when Compare runs is clicked, and returns to canvas", () => {
    render(<WorkflowView />);

    fireEvent.click(screen.getByRole("button", { name: "Compare runs" }));
    expect(screen.getByText("Saved workflow runs")).toBeInTheDocument();
    expect(screen.getByText(/run-aaaa/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back to canvas" }));
    expect(screen.queryByText("Saved workflow runs")).toBeNull();
  });

  it("lets two runs be compared from within Canvas (auto-selected, since exactly two exist)", () => {
    const compareWorkflowRuns = vi.fn().mockImplementation(async () => {
      useWorkspaceStore.setState({
        workflowRunComparison: {
          status: "ok",
          run_ids: ["run-aaaaaaaa", "run-bbbbbbbb"],
          metrics: [],
          steps: [],
          config_diff: {},
        },
      });
    });
    useWorkspaceStore.setState({ compareWorkflowRuns });
    render(<WorkflowView />);
    fireEvent.click(screen.getByRole("button", { name: "Compare runs" }));

    // CompareView auto-selects the first two runs when none are selected yet.
    const compareTrigger = screen.getByRole("button", { name: "Compare runs" });
    expect(compareTrigger).not.toBeDisabled();
    fireEvent.click(compareTrigger);

    expect(compareWorkflowRuns).toHaveBeenCalled();
  });
});

describe("Canvas — Load from sweep", () => {
  it("opens the picker and lists sweeps from useSweepStore", () => {
    render(<WorkflowView />);

    fireEvent.click(screen.getByRole("button", { name: "Load from sweep" }));

    expect(screen.getByText(/sweep-1/)).toBeInTheDocument();
    expect(screen.getByText(/6\/8 admissible/)).toBeInTheDocument();
  });

  it("selecting a sweep previews its scenarios", () => {
    render(<WorkflowView />);
    fireEvent.click(screen.getByRole("button", { name: "Load from sweep" }));

    fireEvent.change(screen.getByRole("combobox", { name: "Sweep" }), { target: { value: "sweep-1" } });

    expect(useSweepStore.getState().previewSweepScenarios).toHaveBeenCalledWith(
      expect.any(String),
      "s1",
      "sweep-1",
    );
  });

  it("loading a chosen scenario calls loadScenarioIntoCanvas and closes the picker", async () => {
    render(<WorkflowView />);
    fireEvent.click(screen.getByRole("button", { name: "Load from sweep" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Sweep" }), { target: { value: "sweep-1" } });

    const scenarioRadio = await screen.findByRole("radio", { name: /c1a2b3c4/ });
    fireEvent.click(scenarioRadio);
    fireEvent.click(screen.getByRole("button", { name: "Load" }));

    expect(useWorkspaceStore.getState().loadScenarioIntoCanvas).toHaveBeenCalledWith("sweep-1", "c1a2b3c4");
    expect(screen.queryByRole("button", { name: "Load" })).toBeNull();
  });

  it("shows an inadmissible scenario too, rather than hiding it", async () => {
    render(<WorkflowView />);
    fireEvent.click(screen.getByRole("button", { name: "Load from sweep" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Sweep" }), { target: { value: "sweep-1" } });

    expect(await screen.findByText(/d5e6f7a8/)).toBeInTheDocument();
    expect(screen.getByText(/excluded/i)).toBeInTheDocument();
  });

  it("no longer offers to auto-build a default workflow in the empty-canvas hint", () => {
    render(<WorkflowView />);
    expect(screen.queryByText(/prepare a default workflow/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Load from sweep" })).toBeInTheDocument();
  });
});

describe("Canvas — Upload config", () => {
  it("offers an Upload config button", () => {
    render(<WorkflowView />);
    expect(screen.getByRole("button", { name: "Upload config" })).toBeInTheDocument();
  });

  it("reads the chosen file into the Edit config editor and opens it for review, rather than running blind", async () => {
    render(<WorkflowView />);
    const uploaded = JSON.stringify({ site: { hubHeightM: 150 }, scenario: { config_hash: "c9" } }, null, 2);
    const file = new File([uploaded], "scenario.json", { type: "application/json" });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, { target: { files: [file] } });

    const textarea = await screen.findByLabelText("Run configuration JSON");
    expect((textarea as HTMLTextAreaElement).value).toBe(uploaded);
    expect(screen.getByRole("button", { name: "Save and run" })).toBeInTheDocument();
  });

  it("loads an invalid-JSON file's raw text unchanged, so the existing validation catches it on Save and run", async () => {
    render(<WorkflowView />);
    const file = new File(["not valid json {{"], "broken.json", { type: "application/json" });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    const textarea = await screen.findByLabelText("Run configuration JSON");
    expect((textarea as HTMLTextAreaElement).value).toBe("not valid json {{");

    fireEvent.click(screen.getByRole("button", { name: "Save and run" }));
    expect(await screen.findByText("Configuration must be valid JSON.")).toBeInTheDocument();
  });

  it("lets the same file be re-selected after clearing the input", async () => {
    render(<WorkflowView />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["{}"], "again.json", { type: "application/json" });

    fireEvent.change(input, { target: { files: [file] } });
    await screen.findByLabelText("Run configuration JSON");

    expect(input.value).toBe("");
  });
});
