import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock react-plotly.js so jsdom doesn't try to render a real Plotly figure.
vi.mock("react-plotly.js", () => ({
  default: ({ layout }: { layout?: { title?: string } }) => (
    <div data-testid="plotly-stub">{String(layout?.title ?? "")}</div>
  ),
}));

import { PlotFrame } from "../components/common/PlotFrame";
import type { PlotResult } from "../types/analysis";

function makeResult(overrides: Partial<PlotResult> = {}): PlotResult {
  return {
    plotly_json: JSON.stringify({
      data: [{ type: "bar", x: [1, 2, 3], y: [4, 5, 6] }],
      layout: { title: "Test Plot" },
    }),
    png_base64: null,
    title: "Test Plot",
    ...overrides,
  };
}

describe("PlotFrame", () => {
  it("renders a passed-in result without fetching", () => {
    render(<PlotFrame plotName="weibull" params={{}} result={makeResult()} />);
    expect(screen.getByTestId("plotly-stub")).toBeInTheDocument();
    expect(screen.getByTestId("plotly-stub").textContent).toContain("Test Plot");
  });

  it("falls back to PNG when the figure JSON cannot be parsed", () => {
    const result = makeResult({
      plotly_json: "not-valid-json{",
      png_base64: "iVBORw0KGgoAAAANS",
      title: "Fallback",
    });
    render(<PlotFrame plotName="windrose" params={{}} result={result} />);
    expect(screen.getByAltText("Fallback")).toBeInTheDocument();
    expect(screen.queryByTestId("plotly-stub")).not.toBeInTheDocument();
  });

  it("shows an error when the fetch rejects", async () => {
    const { useWorkspaceStore } = await import("../store/useWorkspaceStore");
    useWorkspaceStore.setState({
      session: { session_id: "s1" } as never,
      fetchPlot: vi.fn(async () => {
        throw new Error("boom");
      }) as never,
    });

    render(<PlotFrame plotName="diurnal" params={{ sensor_names: "Spd_80m" }} />);
    await waitFor(() => {
      expect(screen.getByText("diurnal")).toBeInTheDocument();
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });
});
