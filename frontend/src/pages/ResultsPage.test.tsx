import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, configApi, resultsApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { ResultsPage } from "./ResultsPage";

vi.mock("../components/common/PlotlyFigure", () => ({
  PlotlyFigure: ({ plot, emptyTitle }: { plot?: { title?: string } | null; emptyTitle: string }) => (
    <div>{plot ? `plot:${plot.title}` : emptyTitle}</div>
  ),
}));

vi.mock("../components/common/GeoJsonMap", () => ({
  GeoJsonMap: ({ featureCollection, emptyTitle }: { featureCollection?: { features?: unknown[] } | null; emptyTitle: string }) => (
    <div>{featureCollection ? `map:${featureCollection.features?.length ?? 0}` : emptyTitle}</div>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    uploadsApi: {
      ...actual.uploadsApi,
      getSensors: vi.fn(),
    },
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
    analysisApi: {
      ...actual.analysisApi,
      listScenarios: vi.fn(),
      saveScenario: vi.fn(),
      deleteScenario: vi.fn(),
    },
    resultsApi: {
      ...actual.resultsApi,
      getLtcResults: vi.fn(),
      getSiteMap: vi.fn(),
      getPlot: vi.fn(),
      exportRunconfig: vi.fn(),
    },
  };
});

describe("ResultsPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.spyOn(window, "open").mockImplementation(() => null);
    useWorkspaceStore.getState().setLatestUncertainty({
      total_uncertainty_pct: 8.2,
      components: {
        measurement: 2.1,
        vertical_extrapolation: 1.8,
        mcp: 4.2,
        future_variability: 5.1,
      },
      p_factors: { p50: 1, p75: 1.03, p90: 1.08, p99: 1.2 },
      inputs: {
        measurement_height_m: 100,
        hub_height_m: 140,
        shear_method: "simple_power_law",
        mcp_r_squared: 0.9,
        concurrent_months: 12,
        iav_pct: 6,
        algorithm: "linear_least_squares",
        is_interpolation: false,
      },
    });
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        { name: "Wind_100m", height_m: 100, sensor_type: "wind_speed", data_coverage_pct: 99, record_count: 1000 },
        { name: "Wind_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 98, record_count: 1000 },
        { name: "Dir_100m", height_m: 100, sensor_type: "wind_direction", data_coverage_pct: 99, record_count: 1000 },
      ],
    });
    vi.mocked(configApi.get).mockResolvedValue({ project_name: "North Ridge", hub_height_m: 140 });
    vi.mocked(analysisApi.listScenarios).mockResolvedValue({ scenarios: [] });
    vi.mocked(analysisApi.saveScenario).mockResolvedValue({ status: "ok", name: "Scenario A" });
    vi.mocked(analysisApi.deleteScenario).mockResolvedValue({ status: "ok" });
    vi.mocked(resultsApi.getLtcResults).mockResolvedValue({
      results: [
        { algorithm: "linear_least_squares", metrics: { mean: 8.5 }, result_file: "results/lls.csv", rows: 8760 },
      ],
    });
    vi.mocked(resultsApi.getSiteMap).mockResolvedValue({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [56.78, 12.34] },
          properties: { type: "mast" },
        },
      ],
    });
    vi.mocked(resultsApi.getPlot).mockImplementation(async (_sessionId, plotName) => ({
      title: plotName,
      plotly_json: JSON.stringify({ data: [], layout: {}, config: {} }),
      png_base64: null,
    }));
    vi.mocked(resultsApi.exportRunconfig).mockResolvedValue({
      status: "ok",
      file_path: "exports/runconfig.json",
      runconfig: { project_name: "North Ridge" },
    });
  });

  it("shows the empty state when no session exists", () => {
    renderWithProviders(<ResultsPage />);

    expect(screen.getByText("Session required")).toBeTruthy();
  });

  it("renders stored result outputs and file metadata", async () => {
    useWorkspaceStore.getState().setSessionId("session-results");
    renderWithProviders(<ResultsPage />);

    expect(await screen.findByText("plot:annual_means")).toBeTruthy();
    expect(screen.getByText("plot:ltc_comparison")).toBeTruthy();
    expect(screen.getByText("plot:uncertainty_breakdown")).toBeTruthy();
    expect(screen.getByText("map:1")).toBeTruthy();
    expect(screen.getByText("results/lls.csv")).toBeTruthy();
  });

  it("exports runconfig and requests a custom plot", async () => {
    useWorkspaceStore.getState().setSessionId("session-results");
    renderWithProviders(<ResultsPage />);

    await screen.findByText("plot:annual_means");
    fireEvent.change(screen.getByDisplayValue("weibull"), { target: { value: "scatter" } });
    fireEvent.change(screen.getByLabelText("Sensor name"), { target: { value: "Wind_80m" } });
    fireEvent.click(screen.getByRole("button", { name: "Render Custom Plot" }));

    await waitFor(() => {
      expect(resultsApi.getPlot).toHaveBeenCalledWith("session-results", "scatter", {
        sensor_name: "Wind_80m",
        speed_sensor: "Wind_100m",
        direction_sensor: "Dir_100m",
        sensor_names: "Wind_100m",
        sensor_a: "Wind_100m",
        sensor_b: "Wind_80m",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Export Runconfig" }));
    await waitFor(() => {
      expect(resultsApi.exportRunconfig).toHaveBeenCalledWith("session-results");
    });

    fireEvent.click(screen.getByRole("button", { name: "Download Runconfig JSON" }));

    expect(window.open).toHaveBeenCalledWith("/api/sessions/session-results/exports/runconfig", "_blank", "noopener");
  });

  it("disables scenario save when the name is empty", async () => {
    useWorkspaceStore.getState().setSessionId("session-results");
    renderWithProviders(<ResultsPage />);

    expect((await screen.findByRole("button", { name: "Save Current as Scenario" })) as HTMLButtonElement).toHaveProperty("disabled", true);
  });

  it("renders saved scenario rows and the comparison plot", async () => {
    useWorkspaceStore.getState().setSessionId("session-results");
    vi.mocked(analysisApi.listScenarios).mockResolvedValue({
      scenarios: [
        {
          name: "Base",
          created_at: "2026-04-09T00:00:00Z",
          config: {
            shear_method: "simple_power_law",
            shear_aggregation: "momm",
            hub_height_m: 140,
            sensors_used: ["Wind_100m"],
            ltc_algorithm: "linear_least_squares",
            ltc_source: "linear_least_squares",
            cutoff_year: null,
          },
          results: {
            long_term_mean_speed: 8.5,
            ensemble_mean_speed: 8.4,
            total_uncertainty_pct: 8.2,
            p50: 1,
            p75: 0.94,
            p90: 0.89,
            p99: 0.8,
            measurement_uncertainty_pct: 2.1,
            vertical_uncertainty_pct: 1.8,
            mcp_uncertainty_pct: 4.2,
            future_uncertainty_pct: 5.1,
          },
        },
        {
          name: "Tall hub",
          created_at: "2026-04-09T00:05:00Z",
          config: {
            shear_method: "simple_power_law",
            shear_aggregation: "momm",
            hub_height_m: 160,
            sensors_used: ["Wind_100m"],
            ltc_algorithm: "linear_least_squares",
            ltc_source: "linear_least_squares",
            cutoff_year: null,
          },
          results: {
            long_term_mean_speed: 8.8,
            ensemble_mean_speed: 8.6,
            total_uncertainty_pct: 8.7,
            p50: 1,
            p75: 0.93,
            p90: 0.88,
            p99: 0.79,
            measurement_uncertainty_pct: 2.1,
            vertical_uncertainty_pct: 1.9,
            mcp_uncertainty_pct: 4.4,
            future_uncertainty_pct: 5.1,
          },
        },
      ],
    });
    vi.mocked(resultsApi.getPlot).mockImplementation(async (_sessionId, plotName) => ({
      title: plotName,
      plotly_json: JSON.stringify({ data: [], layout: {}, config: {} }),
      png_base64: null,
    }));

    renderWithProviders(<ResultsPage />);

    expect(await screen.findByText("Base")).toBeTruthy();
    expect(screen.getByText("Tall hub")).toBeTruthy();
    await waitFor(() => {
      expect(resultsApi.getPlot).toHaveBeenCalledWith("session-results", "scenario_comparison", {});
    });
  });
});