// Covers the post-revamp navigation contract: tab order, the optional cleaning
// step, and the reanalysis provider now living on the Data import page.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

// Block real network calls from views that auto-fetch on mount.
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { PhaseTabs } from "../components/PhaseTabs";
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
    activeTab: "import",
    config: createDefaultWindAnalysisConfig(),
  });
});

describe("PhaseTabs ordering", () => {
  it("puts cleaning and the Analysis Engine ahead of Canvas and the Stepper", () => {
    render(<PhaseTabs />);

    const labels = screen
      .getAllByRole("button")
      .map((button) => button.textContent);

    expect(labels).toEqual([
      "Data import",
      "Data cleaning",
      "Analysis Engine",
      "Canvas",
      "Stepper",
      "Results",
      "Copilot",
      "Sensor Overview",
      "Compare",
      "How To",
    ]);
  });

  it("selects the cleaning tab when it is clicked", () => {
    render(<PhaseTabs />);

    fireEvent.click(screen.getByRole("button", { name: "Data cleaning" }));

    expect(useWorkspaceStore.getState().activeTab).toBe("cleaning");
  });
});

describe("Data cleaning is optional", () => {
  it("offers a skip action that jumps straight to the Analysis Engine", () => {
    useWorkspaceStore.setState({ activeTab: "cleaning" });
    render(<CleaningView />);

    expect(screen.getByText("Data cleaning is optional")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /skip cleaning/i }));

    expect(useWorkspaceStore.getState().activeTab).toBe("engine");
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
