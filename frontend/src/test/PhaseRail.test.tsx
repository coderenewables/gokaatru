// The 3-phase primary nav (design doc: Prepare / Run / Interrogate) replacing the old
// 10-tab PhaseTabs. Canvas and Copilot stay reachable as their own rail entries;
// Compare is gone from the top level (relocated into Canvas — see WorkflowView.test.tsx).
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { PhaseRail } from "../components/PhaseRail";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

beforeEach(() => {
  useWorkspaceStore.setState({
    activePhase: "prepare",
    selectedStage: "cleaning",
    session: { session_id: "s1" } as never,
  });
});

describe("PhaseRail", () => {
  it("renders exactly 5 top-level nav entries, and no Compare entry", () => {
    render(<PhaseRail />);
    expect(screen.getByRole("button", { name: /Prepare/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Interrogate/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Canvas/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copilot/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /compare/i })).toBeNull();
  });

  it("marks Prepare as the current entry by default", () => {
    render(<PhaseRail />);
    expect(screen.getByRole("button", { name: /Prepare/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Run/ })).not.toHaveAttribute("aria-current", "page");
  });

  it("clicking Run updates activePhase and marks Run current", () => {
    render(<PhaseRail />);
    fireEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(useWorkspaceStore.getState().activePhase).toBe("run");
    expect(screen.getByRole("button", { name: /Run/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Prepare/ })).not.toHaveAttribute("aria-current", "page");
  });

  it("clicking Interrogate and Canvas and Copilot switch phases", () => {
    render(<PhaseRail />);
    fireEvent.click(screen.getByRole("button", { name: /Interrogate/ }));
    expect(useWorkspaceStore.getState().activePhase).toBe("interrogate");
    fireEvent.click(screen.getByRole("button", { name: /Canvas/ }));
    expect(useWorkspaceStore.getState().activePhase).toBe("canvas");
    fireEvent.click(screen.getByRole("button", { name: /Copilot/ }));
    expect(useWorkspaceStore.getState().activePhase).toBe("copilot");
  });
});
