// ⌘K command palette (design doc: "Ask or jump") — search-as-you-type over phases,
// pipeline stages, sweep presets, metrics and gates, all read from real data; free text
// falls through to "Ask Copilot". No mockup-only entries (design notes, Smoke test, Compare).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CommandPalette } from "../components/CommandPalette";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { useSweepStore } from "../store/useSweepStore";

beforeEach(() => {
  useWorkspaceStore.setState({
    paletteOpen: false,
    activePhase: "prepare",
    selectedStage: "cleaning",
    prepareSection: "data",
    session: { session_id: "s1" } as never,
    sendChatMessage: vi.fn().mockResolvedValue(undefined),
  });
  useSweepStore.setState({ metric: "long_term_mean_speed_mps" });
});

describe("CommandPalette", () => {
  it("is closed by default, opens on Ctrl+K, and closes on Escape", () => {
    render(<CommandPalette />);
    expect(screen.queryByPlaceholderText(/jump to/i)).toBeNull();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByPlaceholderText(/jump to/i)).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByPlaceholderText(/jump to/i)).toBeNull();
  });

  it("filters to only the matching stage when searching 'cleaning'", () => {
    useWorkspaceStore.setState({ paletteOpen: true });
    render(<CommandPalette />);

    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "cleaning" } });

    expect(screen.getByRole("button", { name: /Data cleaning/ })).toBeInTheDocument();
    expect(screen.queryByText("Long-Term Correction")).toBeNull();
    expect(screen.queryByText("Run", { selector: ".palette-label" })).toBeNull();
  });

  it("selecting a phase entry navigates and closes the palette", () => {
    useWorkspaceStore.setState({ paletteOpen: true });
    render(<CommandPalette />);

    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "Run" } });
    fireEvent.click(screen.getByRole("button", { name: /^phase Run phase$/ }));

    expect(useWorkspaceStore.getState().activePhase).toBe("run");
    expect(useWorkspaceStore.getState().paletteOpen).toBe(false);
  });

  it("selecting a metric switches Interrogate's metric and navigates there", () => {
    useWorkspaceStore.setState({ paletteOpen: true });
    render(<CommandPalette />);

    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "gross AEP" } });
    fireEvent.click(screen.getByRole("button", { name: /Indicative gross AEP/ }));

    expect(useSweepStore.getState().metric).toBe("indicative_gross_aep_mwh");
    expect(useWorkspaceStore.getState().activePhase).toBe("interrogate");
  });

  it("asking Copilot sends the typed text and switches to the Copilot phase", () => {
    useWorkspaceStore.setState({ paletteOpen: true });
    render(<CommandPalette />);

    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "why is the spread so wide" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask Copilot/ }));

    expect(useWorkspaceStore.getState().sendChatMessage).toHaveBeenCalledWith("why is the spread so wide");
    expect(useWorkspaceStore.getState().activePhase).toBe("copilot");
  });

  it("never surfaces mockup-only entries (design notes, Smoke test, Compare) in the results list", () => {
    useWorkspaceStore.setState({ paletteOpen: true });
    const { container } = render(<CommandPalette />);
    for (const query of ["design", "smoke", "compare"]) {
      fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: query } });
      const results = container.querySelector(".palette-results");
      // Only the empty-state message may appear — no real command matches these queries,
      // and the free-text "Ask Copilot" echo (which legitimately contains the typed word)
      // lives outside .palette-results, so it's excluded from this check on purpose.
      expect(results?.querySelector(".palette-item")).toBeNull();
    }
  });
});
