import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, configApi, resultsApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { LtcPage } from "./LtcPage";

vi.mock("../components/common/PlotlyFigure", () => ({
  PlotlyFigure: ({ plot, emptyTitle }: { plot?: { title?: string } | null; emptyTitle: string }) => (
    <div>{plot ? plot.title : emptyTitle}</div>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
    uploadsApi: {
      ...actual.uploadsApi,
      getSensors: vi.fn(),
    },
    analysisApi: {
      ...actual.analysisApi,
      runLtc: vi.fn(),
      runEnsemble: vi.fn(),
      runClipping: vi.fn(),
      analyzeHomogeneity: vi.fn(),
      applyHomogeneity: vi.fn(),
      calculateUncertainty: vi.fn(),
    },
    resultsApi: {
      ...actual.resultsApi,
      getLtcResults: vi.fn(),
      getEnsembleResults: vi.fn(),
      getPlot: vi.fn(),
    },
  };
});

describe("LtcPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.spyOn(window, "open").mockImplementation(() => null);
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        { name: "Wind_100m", height_m: 100, sensor_type: "wind_speed", data_coverage_pct: 99, record_count: 1000 },
        { name: "Wind_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 97, record_count: 980 },
        { name: "Dir_100m", height_m: 100, sensor_type: "wind_direction", data_coverage_pct: 99, record_count: 1000 },
        { name: "Dir_80m", height_m: 80, sensor_type: "wind_direction", data_coverage_pct: 97, record_count: 980 },
      ],
    });
    vi.mocked(configApi.get).mockResolvedValue({ hub_height_m: 150 });
    vi.mocked(resultsApi.getLtcResults).mockResolvedValue({ results: [] });
    vi.mocked(resultsApi.getEnsembleResults).mockResolvedValue({
      available: false,
      reference_columns: ["Spd_100m_hub", "Dir_100m", "sp", "t2m", "d2m"],
    });
    vi.mocked(resultsApi.getPlot).mockImplementation(async (_sessionId, plotName, body) => ({
      plotly_json: JSON.stringify({ data: [{ x: [1], y: [2], type: "scatter" }], layout: {} }),
      png_base64: null,
      title:
        plotName === "ltc_scatter"
          ? `LTC Scatter — ${String((body as { algorithm?: string }).algorithm ?? "linear_least_squares")}`
          : plotName === "ltc_residuals"
            ? `LTC Residuals — ${String((body as { algorithm?: string }).algorithm ?? "linear_least_squares")}`
            : plotName === "ltc_monthly"
              ? "Monthly LTC Comparison"
              : plotName === "ltc_convergence"
                ? "Annual Convergence"
                : "Uncertainty Tornado",
    }));
    vi.mocked(analysisApi.runLtc).mockResolvedValue({ status: "ok", algorithm: "linear_least_squares" });
    vi.mocked(analysisApi.runEnsemble).mockResolvedValue({ status: "ok" });
    vi.mocked(analysisApi.runClipping).mockResolvedValue({
      optimal_start_year: 2010,
      min_uncertainty: 0.1,
      iav: 6,
      analysis_data: [],
    });
    vi.mocked(analysisApi.analyzeHomogeneity).mockResolvedValue({ datasets: [] });
    vi.mocked(analysisApi.applyHomogeneity).mockResolvedValue({ status: "ok", rows_before: 10, rows_after: 8, cutoff_year: 2010 });
    vi.mocked(analysisApi.calculateUncertainty).mockResolvedValue({
      total_uncertainty_pct: 10,
      components: { measurement: 2, vertical_extrapolation: 1, mcp: 5, future_variability: 2 },
      p_factors: { p50: 1, p75: 1.1, p90: 1.2, p99: 1.3 },
      inputs: {
        measurement_height_m: 100,
        hub_height_m: 150,
        shear_method: "simple_power_law",
        mcp_r_squared: 0.9,
        concurrent_months: 12,
        iav_pct: 6,
        algorithm: "linear_least_squares",
        is_interpolation: false,
      },
    });
  });

  it("shows measured wind and direction sensors as dropdowns and uses their selections", async () => {
    useWorkspaceStore.getState().setSessionId("session-ltc");
    renderWithProviders(<LtcPage />);

    const shortColumnSelect = (await screen.findByLabelText("Measured short column")) as HTMLSelectElement;
    const directionColumnSelect = screen.getByLabelText("Measured direction column") as HTMLSelectElement;
    const ensembleColumnSelect = screen.getByLabelText("Measured column for ensemble") as HTMLSelectElement;

    await waitFor(() => {
      expect(shortColumnSelect.value).toBe("Wind_100m");
      expect(directionColumnSelect.value).toBe("Dir_100m");
      expect(ensembleColumnSelect.value).toBe("Wind_100m");
    });

    fireEvent.change(shortColumnSelect, { target: { value: "Wind_80m" } });
    fireEvent.change(directionColumnSelect, { target: { value: "Dir_80m" } });
    fireEvent.change(ensembleColumnSelect, { target: { value: "Wind_80m" } });
    fireEvent.change(screen.getByLabelText("Long reference column"), { target: { value: "Spd_100m_hub" } });
    fireEvent.change(screen.getByLabelText("Reference direction column"), { target: { value: "Dir_100m" } });

    fireEvent.click(screen.getByRole("button", { name: "Run linear_least_squares" }));

    await waitFor(() => {
      expect(analysisApi.runLtc).toHaveBeenCalledWith("session-ltc", "linear_least_squares", {
        short_col: "Wind_80m",
        long_col: "Spd_100m_hub",
        short_dir_col: "Dir_80m",
        long_dir_col: "Dir_100m",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Run Ensemble" }));

    await waitFor(() => {
      expect(analysisApi.runEnsemble).toHaveBeenCalledWith("session-ltc", "Wind_80m");
    });
  });

  it("shows the diagnostic panel when LTC results are available", async () => {
    useWorkspaceStore.getState().setSessionId("session-ltc");
    vi.mocked(resultsApi.getLtcResults).mockResolvedValue({
      results: [
        {
          algorithm: "linear_least_squares",
          rows: 120,
          metrics: { r_squared: 0.92, concurrent_points: 120 },
        },
      ],
    });

    renderWithProviders(<LtcPage />);

    expect(await screen.findByText("LTC Scatter — linear_least_squares")).toBeTruthy();
    expect(await screen.findByText("LTC Residuals — linear_least_squares")).toBeTruthy();
    expect(await screen.findByText("Monthly LTC Comparison")).toBeTruthy();
    expect(await screen.findByText("Annual Convergence")).toBeTruthy();
  });

  it("updates the algorithm help text when the selection changes", async () => {
    useWorkspaceStore.getState().setSessionId("session-ltc");
    renderWithProviders(<LtcPage />);

    expect(await screen.findByText(/Iteratively reweighted least squares using Huber loss/i)).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: /Algorithm/i }), { target: { value: "xgboost" } });
    expect(await screen.findByText(/Gradient-boosted trees with temporal, directional, and meteorological features/i)).toBeTruthy();
  });

  it("renders the uncertainty tornado after uncertainty results are available", async () => {
    useWorkspaceStore.getState().setSessionId("session-ltc");
    useWorkspaceStore.getState().setLatestUncertainty({
      total_uncertainty_pct: 10,
      components: { measurement: 2, vertical_extrapolation: 1, mcp: 5, future_variability: 2 },
      p_factors: { p50: 1, p75: 0.9326, p90: 0.8718, p99: 0.7674 },
      inputs: {
        measurement_height_m: 100,
        hub_height_m: 150,
        shear_method: "simple_power_law",
        mcp_r_squared: 0.9,
        concurrent_months: 12,
        iav_pct: 6,
        algorithm: "linear_least_squares",
        is_interpolation: false,
      },
    });

    renderWithProviders(<LtcPage />);

    expect(await screen.findByText("Uncertainty Tornado")).toBeTruthy();
  });

  it("opens LTC and ensemble export URLs for the active session", async () => {
    useWorkspaceStore.getState().setSessionId("session-ltc");
    vi.mocked(resultsApi.getLtcResults).mockResolvedValue({
      results: [
        {
          algorithm: "linear_least_squares",
          rows: 120,
          metrics: { r_squared: 0.92, concurrent_points: 120 },
        },
      ],
    });
    vi.mocked(resultsApi.getEnsembleResults).mockResolvedValue({
      available: true,
      reference_columns: ["Spd_100m_hub", "Dir_100m"],
    });

    renderWithProviders(<LtcPage />);

    await screen.findByText("LTC Scatter — linear_least_squares");
    fireEvent.click(screen.getByRole("button", { name: "CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export Ensemble CSV" }));

    expect(window.open).toHaveBeenNthCalledWith(1, "/api/sessions/session-ltc/exports/ltc/linear_least_squares", "_blank", "noopener");
    expect(window.open).toHaveBeenNthCalledWith(2, "/api/sessions/session-ltc/exports/ensemble", "_blank", "noopener");
  });
});