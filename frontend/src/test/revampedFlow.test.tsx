// Covers the post-revamp navigation contract: tab order, the optional cleaning
// step, and the reanalysis provider now living on the Data import page.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

// Block real network calls from views that auto-fetch on mount.
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { CleaningView } from "../components/stages/CleaningView";
import { DataLoadView } from "../components/stages/DataLoadView";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import type { SensorRow } from "../types/analysis";

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
];

beforeEach(() => {
  useWorkspaceStore.setState({
    session: { session_id: "s1", session_id_short: "s1" } as never,
    summary: { completed_steps: [], hub_height_m: 120 } as never,
    busyLabel: null,
    sensors: SENSORS,
    activePhase: "prepare",
    selectedStage: "data",
    prepareSection: "data",
    config: createDefaultWindAnalysisConfig(),
  });
});

// Top-level nav ordering/selection is covered by PhaseRail.test.tsx now that Data import
// and Data cleaning are Prepare-phase sections rather than their own tabs.

describe("Data cleaning is optional", () => {
  it("offers a skip action that jumps straight to the Run phase", () => {
    useWorkspaceStore.setState({ activePhase: "prepare", selectedStage: "cleaning", prepareSection: "pipeline" });
    render(<CleaningView />);

    expect(screen.getByText("Data cleaning is optional")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /skip cleaning/i }));

    expect(useWorkspaceStore.getState().activePhase).toBe("run");
  });

  it("offers a link to sensor review that switches Prepare's section without leaving the phase", () => {
    useWorkspaceStore.setState({ activePhase: "prepare", selectedStage: "cleaning", prepareSection: "pipeline" });
    render(<CleaningView />);

    fireEvent.click(screen.getByRole("button", { name: /open sensor review/i }));

    expect(useWorkspaceStore.getState().activePhase).toBe("prepare");
    expect(useWorkspaceStore.getState().prepareSection).toBe("sensors");
  });
});

describe("Reanalysis provider on the Data import page", () => {
  it("renders the provider choice and writes it through to runconfig-backed state", () => {
    render(<DataLoadView />);

    const panel = screen.getByText("Long-term reference").closest("section");
    expect(panel).not.toBeNull();

    const provider = within(panel as HTMLElement).getByLabelText("Provider");
    expect(provider).toHaveValue("brighthub");

    fireEvent.change(provider, { target: { value: "earthdatahub" } });

    expect(useWorkspaceStore.getState().config.reanalysis.acquisitionSource).toBe("earthdatahub");
  });

  it("saves and sets up rather than running the model", () => {
    render(<DataLoadView />);

    expect(screen.getByRole("button", { name: "Save config and setup" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run model/i })).toBeNull();
  });
});
