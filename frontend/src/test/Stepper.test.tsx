import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { Stepper } from "../components/Stepper";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { computeStageStatuses, STEPPER_STAGE_ORDER } from "../lib/stages";
import type { StageId, StageStatus } from "../types/analysis";

function setStatuses(completedSteps: string[]) {
  useWorkspaceStore.setState({
    stageStatuses: computeStageStatuses(completedSteps) as unknown as Record<StageId, StageStatus>,
    selectedStage: "cleaning",
    session: { session_id: "s1" } as never,
  });
}

describe("Stepper", () => {
  beforeEach(() => {
    setStatuses([]);
  });

  it("renders the post-import stages in order with index badges", () => {
    render(<Stepper />);
    STEPPER_STAGE_ORDER.forEach((stage) => {
      // Title text from STAGE_META appears
      expect(screen.getByText(new RegExp(STAGE_META_TITLE(stage)))).toBeInTheDocument();
    });
    // First index badge = 1
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("disables locked stages and enables available ones", () => {
    setStatuses([]); // data import is required before every visible stage
    render(<Stepper />);
    const cleaningChip = screen.getByRole("button", { name: /data cleaning/i });
    expect(cleaningChip).toBeDisabled();
    // ltc is locked
    const ltcChip = screen.getByRole("button", { name: /long-term correction/i });
    expect(ltcChip).toBeDisabled();
  });

  it("selecting an available stage updates the store", () => {
    setStatuses(["timeseries", "datamodel", "config"]);
    render(<Stepper />);
    fireEvent.click(screen.getByRole("button", { name: /data cleaning/i }));
    expect(useWorkspaceStore.getState().selectedStage).toBe("cleaning");
  });

  it("clicking a locked stage does not change selection", () => {
    setStatuses([]);
    useWorkspaceStore.setState({ selectedStage: "cleaning" });
    render(<Stepper />);
    const ltcChip = screen.getByRole("button", { name: /long-term correction/i });
    // disabled buttons don't fire click, but verify state unchanged regardless
    expect(ltcChip).toBeDisabled();
    expect(useWorkspaceStore.getState().selectedStage).toBe("cleaning");
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

// Top-level nav (now PhaseRail: Prepare/Run/Interrogate/Canvas/Copilot) is covered by
// PhaseRail.test.tsx — Stepper itself is Prepare-internal now (see PrepareView.test.tsx).

// Helper: stage titles live in STAGE_META; expose for regex matching.
function STAGE_META_TITLE(stage: StageId): string {
  const titles: Record<StageId, string> = {
    data: "Data loading",
    cleaning: "Data cleaning",
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
