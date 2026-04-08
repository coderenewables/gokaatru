import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, resultsApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { LtcPage } from "./LtcPage";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
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
    },
  };
});

describe("LtcPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        { name: "Wind_100m", height_m: 100, sensor_type: "wind_speed", data_coverage_pct: 99, record_count: 1000 },
        { name: "Wind_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 97, record_count: 980 },
        { name: "Dir_100m", height_m: 100, sensor_type: "wind_direction", data_coverage_pct: 99, record_count: 1000 },
        { name: "Dir_80m", height_m: 80, sensor_type: "wind_direction", data_coverage_pct: 97, record_count: 980 },
      ],
    });
    vi.mocked(resultsApi.getLtcResults).mockResolvedValue({ results: [] });
    vi.mocked(resultsApi.getEnsembleResults).mockResolvedValue({ available: false });
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
    fireEvent.change(screen.getByDisplayValue("Spd_100m"), { target: { value: "ERA5_WS" } });
    fireEvent.change(screen.getByDisplayValue("Dir_100m"), { target: { value: "ERA5_WD" } });

    fireEvent.click(screen.getByRole("button", { name: "Run linear_least_squares" }));

    await waitFor(() => {
      expect(analysisApi.runLtc).toHaveBeenCalledWith("session-ltc", "linear_least_squares", {
        short_col: "Wind_80m",
        long_col: "ERA5_WS",
        short_dir_col: "Dir_80m",
        long_dir_col: "ERA5_WD",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Run Ensemble" }));

    await waitFor(() => {
      expect(analysisApi.runEnsemble).toHaveBeenCalledWith("session-ltc", "Wind_80m");
    });
  });
});