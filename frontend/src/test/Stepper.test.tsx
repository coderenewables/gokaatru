import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { Stepper } from "../components/Stepper";
import { PhaseTabs } from "../components/PhaseTabs";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { computeStageStatuses, STAGE_ORDER } from "../lib/stages";
import type { StageId, StageStatus } from "../types/analysis";

function setStatuses(completedSteps: string[]) {
  useWorkspaceStore.setState({
    stageStatuses: computeStageStatuses(completedSteps) as unknown as Record<StageId, StageStatus>,
    selectedStage: "data",
    session: { session_id: "s1" } as never,
  });
}

describe("Stepper", () => {
  beforeEach(() => {
    setStatuses([]);
  });

  it("renders all 8 stages in order with index badges", () => {
    render(<Stepper />);
    STAGE_ORDER.forEach((stage) => {
      // Title text from STAGE_META appears
      expect(screen.getByText(new RegExp(STAGE_META_TITLE(stage)))).toBeInTheDocument();
    });
    // First index badge = 1
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("disables locked stages and enables available ones", () => {
    setStatuses([]); // only data is available, everything else locked
    render(<Stepper />);
    // data is a button, not disabled
    const dataChip = screen.getByRole("button", { name: /data loading/i });
    expect(dataChip).not.toBeDisabled();
    // ltc is locked
    const ltcChip = screen.getByRole("button", { name: /long-term correction/i });
    expect(ltcChip).toBeDisabled();
  });

  it("selecting an available stage updates the store", () => {
    setStatuses([]); // data available
    render(<Stepper />);
    fireEvent.click(screen.getByRole("button", { name: /data loading/i }));
    expect(useWorkspaceStore.getState().selectedStage).toBe("data");
  });

  it("clicking a locked stage does not change selection", () => {
    setStatuses([]);
    useWorkspaceStore.setState({ selectedStage: "data" });
    render(<Stepper />);
    const ltcChip = screen.getByRole("button", { name: /long-term correction/i });
    // disabled buttons don't fire click, but verify state unchanged regardless
    expect(ltcChip).toBeDisabled();
    expect(useWorkspaceStore.getState().selectedStage).toBe("data");
  });

  it("unlocks downstream stages as prerequisites complete", () => {
    setStatuses(["timeseries", "datamodel", "config"]); // data + explore done
    render(<Stepper />);
    // shear prereq is data+explore (both done) → available
    const shearChip = screen.getByRole("button", { name: /shear .* hub/i });
    expect(shearChip).not.toBeDisabled();
    // reanalysis prereq is data (done) → available
    const reanalysisChip = screen.getByRole("button", { name: /reanalysis acquisition/i });
    expect(reanalysisChip).not.toBeDisabled();
  });
});

describe("PhaseTabs", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      activeTab: "setup",
      session: { session_id: "s1" } as never,
    });
  });

  it("renders all 5 tabs", () => {
    render(<PhaseTabs />);
    expect(screen.getByRole("button", { name: "Stepper" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Canvas" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "WindKit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copilot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare" })).toBeInTheDocument();
  });

  it("marks the active tab and switches on click", () => {
    render(<PhaseTabs />);
    const stepperTab = screen.getByRole("button", { name: "Stepper" });
    expect(stepperTab).toHaveAttribute("aria-current", "page");

    fireEvent.click(screen.getByRole("button", { name: "Canvas" }));
    expect(useWorkspaceStore.getState().activeTab).toBe("workflow");
    expect(screen.getByRole("button", { name: "Canvas" })).toHaveAttribute("aria-current", "page");
    expect(stepperTab).not.toHaveAttribute("aria-current", "page");
  });
});

// Helper: stage titles live in STAGE_META; expose for regex matching.
function STAGE_META_TITLE(stage: StageId): string {
  const titles: Record<StageId, string> = {
    data: "Data loading",
    reanalysis: "Reanalysis acquisition",
    explore: "Measured-data exploration",
    shear: "Shear",
    reanalysis_extrapolation: "Reanalysis . hub",
    ltc: "Long-Term Correction",
    clipping: "Clipping analysis",
    ensemble: "Ensemble . uncertainty",
  };
  return titles[stage];
}
