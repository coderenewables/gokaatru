import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-plotly.js", () => ({
  default: ({ layout }: { layout?: { title?: string } }) => (
    <div data-testid="plotly-stub">{String(layout?.title ?? "")}</div>
  ),
}));

// Block real network calls from auto-fetching views.
vi.spyOn(globalThis, "fetch").mockResolvedValue(
  new Response(JSON.stringify({ detail: "network disabled in test" }), { status: 500 }),
);

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { StageShell } from "../components/stages/StageShell";
import { LtcView } from "../components/stages/LtcView";
import { ClippingView } from "../components/stages/ClippingView";
import { EnsembleView } from "../components/stages/EnsembleView";
import { computeStageStatuses } from "../lib/stages";
import type {
  ClippingReport,
  LtcResultSummary,
  ScenarioSnapshot,
  StageId,
  StageStatus,
  UncertaintyResult,
} from "../types/analysis";

function seedStore(overrides: Record<string, unknown> = {}) {
  useWorkspaceStore.setState({
    session: { session_id: "s1" } as never,
    busyLabel: null,
    sensors: [],
    summary: { completed_steps: [], hub_height_m: 120, project_name: "Test" } as never,
    stageStatuses: computeStageStatuses([]) as unknown as Record<StageId, StageStatus>,
    selectedStage: "ltc",
    config: useWorkspaceStore.getState().config,
    ltcResults: [],
    ensembleSummary: null,
    clippingReport: null,
    clippingColumns: [],
    uncertaintyResult: null,
    scenarios: [],
    ...overrides,
  });
}

const LTC_RESULTS: LtcResultSummary[] = [
  {
    algorithm: "speedsort",
    metrics: { algorithm: "speedsort", r_squared: 0.82, rmse: 0.6, concurrent_points: 8000 },
    result_file: null,
    rows: 70000,
  },
  {
    algorithm: "total_least_squares",
    metrics: { algorithm: "total_least_squares", r_squared: 0.79, rmse: 0.65, concurrent_points: 8000 },
    result_file: null,
    rows: 70000,
  },
];

describe("StageShell Phase E routing", () => {
  beforeEach(() => seedStore());

  it("renders LtcView for the ltc stage", () => {
    useWorkspaceStore.setState({ selectedStage: "ltc" });
    render(<StageShell />);
    expect(screen.getByText("Algorithms")).toBeInTheDocument();
    expect(screen.getByText("Columns")).toBeInTheDocument();
  });

  it("renders ClippingView for the clipping stage", () => {
    useWorkspaceStore.setState({ selectedStage: "clipping" });
    render(<StageShell />);
    expect(screen.getByText("Source & column")).toBeInTheDocument();
  });

  it("renders EnsembleView for the ensemble stage", () => {
    useWorkspaceStore.setState({ selectedStage: "ensemble" });
    render(<StageShell />);
    expect(screen.getByText("Ensemble")).toBeInTheDocument();
    expect(screen.getByText("Uncertainty")).toBeInTheDocument();
    expect(screen.getByText("Scenarios")).toBeInTheDocument();
  });
});

describe("LtcView", () => {
  beforeEach(() => seedStore());

  it("disables run until columns are filled", () => {
    render(<LtcView />);
    const button = screen.getByRole("button", { name: /run/i });
    expect(button).toBeDisabled();
  });

  it("renders metrics cards when LTC results exist", () => {
    seedStore({ ltcResults: LTC_RESULTS });
    render(<LtcView />);
    // "Metrics" section heading appears once LTC results exist.
    expect(screen.getByText("Metrics")).toBeInTheDocument();
    // Both algorithm titles appear as metrics card headings.
    const speedsortHeaders = screen.getAllByText("speedsort");
    expect(speedsortHeaders.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("total_least_squares").length).toBeGreaterThanOrEqual(1);
  });
});

describe("ClippingView", () => {
  beforeEach(() => seedStore());

  it("shows a prompt to run an LTC/ensemble when none available", () => {
    render(<ClippingView />);
    expect(screen.getByText(/run an ltc algorithm or ensemble/i)).toBeInTheDocument();
  });

  it("renders the result + curve when a report is present", () => {
    const report: ClippingReport = {
      optimal_start_year: 2003,
      min_uncertainty: 0.034,
      iav: 0.06,
      analysis_data: [
        { start_year: 2000, n_years: 20, mean_speed: 7.5, iav: 0.06, lta_ratio: 1.0, historic_uncertainty: 0.013, climate_uncertainty: 0.03, combined_uncertainty: 0.033 },
        { start_year: 2003, n_years: 17, mean_speed: 7.6, iav: 0.05, lta_ratio: 1.01, historic_uncertainty: 0.012, climate_uncertainty: 0.028, combined_uncertainty: 0.031 },
      ],
    };
    seedStore({
      ltcResults: LTC_RESULTS,
      clippingColumns: ["corrected_wind_speed"],
      clippingReport: report,
    });
    render(<ClippingView />);
    expect(screen.getByText("Result")).toBeInTheDocument();
    // Optimal start year (2003) appears in the result tile, the chosen-year
    // input value, and the highlighted table row.
    expect(screen.getAllByText("2003").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Combined-uncertainty curve")).toBeInTheDocument();
  });
});

describe("EnsembleView", () => {
  beforeEach(() => seedStore());

  it("warns until ≥2 LTC results exist", () => {
    render(<EnsembleView />);
    expect(screen.getByText(/run ≥2 ltc algorithms/i)).toBeInTheDocument();
  });

  it("renders the P-factors when uncertainty is calculated", () => {
    const uncertainty: UncertaintyResult = {
      total_uncertainty_pct: 8.5,
      components: { measurement: 2.0, vertical_extrapolation: 3.0, mcp: 2.5, future_variability: 1.34 },
      p_factors: { p50: 1.0, p75: 0.943, p90: 0.891, p99: 0.802 },
      inputs: {},
    };
    seedStore({ ltcResults: LTC_RESULTS, uncertaintyResult: uncertainty });
    render(<EnsembleView />);
    expect(screen.getByText("8.50%")).toBeInTheDocument();
    expect(screen.getAllByText(/P50|P75|P90|P99/).length).toBeGreaterThan(0);
  });

  it("lists saved scenarios", () => {
    const scenarios: ScenarioSnapshot[] = [
      { name: "Baseline", created_at: "2026-07-21T00:00:00Z", config: {}, results: {} },
    ];
    seedStore({ ltcResults: LTC_RESULTS, scenarios });
    render(<EnsembleView />);
    expect(screen.getByText("Baseline")).toBeInTheDocument();
  });
});
