import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, resultsApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { DataPage } from "./DataPage";

vi.mock("../components/common/PlotlyFigure", () => ({
  PlotlyFigure: ({ plot, emptyTitle }: { plot?: { title?: string } | null; emptyTitle: string }) => (
    <div>{plot ? plot.title : emptyTitle}</div>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    uploadsApi: {
      ...actual.uploadsApi,
      getSensors: vi.fn(),
      getCoverage: vi.fn(),
      uploadTimeseries: vi.fn(),
      uploadDatamodel: vi.fn(),
    },
    analysisApi: {
      ...actual.analysisApi,
      getCleaningLog: vi.fn(),
      applyCleaning: vi.fn(),
      undoCleaning: vi.fn(),
      getSensorStatistics: vi.fn(),
    },
    resultsApi: {
      ...actual.resultsApi,
      getPlot: vi.fn(),
    },
  };
});

describe("DataPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.spyOn(window, "open").mockImplementation(() => null);
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        {
          name: "Wind_80m",
          height_m: 80,
          sensor_type: "wind_speed",
          data_coverage_pct: 98,
          record_count: 5000,
        },
      ],
    });
    vi.mocked(uploadsApi.getCoverage).mockResolvedValue({
      sensor_name: "Wind_80m",
      total_records: 5000,
      valid_records: 4900,
      coverage_pct: 98,
      gap_count: 3,
      largest_gap_minutes: 45,
      gaps_over_1_hour: 0,
    });
    vi.mocked(analysisApi.getCleaningLog).mockResolvedValue({
      entries: [
        {
          rule_type: "range_check",
          sensor: "Wind_80m",
          records_affected: 12,
          applied_at: "2026-04-07T00:00:00Z",
          params: { min: 0, max: 50 },
          start_date: "2024-01-01",
          end_date: "2024-01-31",
        },
      ],
    });
    vi.mocked(uploadsApi.uploadTimeseries).mockResolvedValue({ status: "ok", file_path: "uploads/timeseries.csv" });
    vi.mocked(uploadsApi.uploadDatamodel).mockResolvedValue({ status: "ok", file_path: "uploads/datamodel.json" });
    vi.mocked(analysisApi.applyCleaning).mockResolvedValue({
      status: "ok",
      rule: "range_check",
      sensor: "Wind_80m",
      records_affected: 12,
    });
    vi.mocked(analysisApi.undoCleaning).mockResolvedValue({ status: "ok" });
    vi.mocked(analysisApi.getSensorStatistics).mockResolvedValue({
      sensor_name: "Wind_80m",
      mean: 8.2,
      median: 8.0,
      std: 1.1,
      min_value: 3.4,
      max_value: 15.8,
      count: 4900,
      coverage_pct: 98,
      weibull_k: 2.1,
      weibull_A: 9.1,
      monthly_means: Array.from({ length: 12 }, (_, index) => index + 1),
      diurnal_means: Array.from({ length: 24 }, (_, index) => index / 10),
      percentiles: { p10: 4.2, p25: 5.8, p50: 8.0, p75: 9.3, p90: 11.2, p99: 14.4 },
    });
    vi.mocked(resultsApi.getPlot).mockImplementation(async (_sessionId, plotName) => ({
      plotly_json: JSON.stringify({ data: [{ x: [1], y: [2], type: "scatter" }], layout: {} }),
      png_base64: null,
      title:
        plotName === "timeseries_preview"
          ? "Data Preview — First 7 Days"
          : plotName === "coverage_timeline"
            ? "Data Coverage Timeline"
            : "Cleaning Overlay — Wind_80m",
    }));
  });

  it("shows the empty state when no session exists", () => {
    renderWithProviders(<DataPage />);

    expect(screen.getByText("Session required")).toBeTruthy();
  });

  it("renders sensor coverage and cleaning log data", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    renderWithProviders(<DataPage />);

    expect(await screen.findByText("45 min")).toBeTruthy();
    expect(screen.getAllByText("Wind_80m").length).toBeGreaterThan(0);
    expect(screen.getAllByText("98.0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("range_check").length).toBeGreaterThan(0);
  });

  it("shows preview plots after upload data is available", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    renderWithProviders(<DataPage />);

    expect(await screen.findByText("Data Preview — First 7 Days")).toBeTruthy();
    expect(await screen.findByText("Data Coverage Timeline")).toBeTruthy();
  });

  it("uploads a timeseries file through the upload dropzone", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    const { container } = renderWithProviders(<DataPage />);

    await screen.findByText("45 min");

    const fileInputs = container.querySelectorAll('input[type="file"]');
    const file = new File(["speed\n8.2"], "timeseries.csv", { type: "text/csv" });
    const fileList = {
      0: file,
      length: 1,
      item: (index: number) => (index === 0 ? file : null),
    };
    fireEvent.change(fileInputs[0] as HTMLInputElement, { target: { files: fileList } });

    await waitFor(() => {
      expect(uploadsApi.uploadTimeseries).toHaveBeenCalledWith("session-1", file, "timeseries.csv");
    });
  });

  it("submits a cleaning rule with the selected sensor and date range", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    renderWithProviders(<DataPage />);

    await screen.findByText("45 min");

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2024-01-01" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2024-01-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply Cleaning Rule" }));

    await waitFor(() => {
      expect(analysisApi.applyCleaning).toHaveBeenCalledWith("session-1", {
        rule_type: "range_check",
        sensor: "Wind_80m",
        params: { min: 0, max: 50 },
        start_date: "2024-01-01",
        end_date: "2024-01-31",
      });
    });
  });

  it("shows typed cleaning inputs instead of a raw JSON textarea", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    const { container } = renderWithProviders(<DataPage />);

    await screen.findByText("45 min");

    expect(screen.getByLabelText("Minimum (m/s)")).toBeTruthy();
    expect(screen.getByLabelText("Maximum (m/s)")).toBeTruthy();
    expect(container.querySelector("textarea")).toBeNull();
  });

  it("shows the sensor detail card after clicking a coverage row", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    renderWithProviders(<DataPage />);

    const sensorCells = await screen.findAllByText("Wind_80m");
    const coverageCell = sensorCells.find((element) => element.closest("tbody") !== null);
    const coverageRow = coverageCell?.closest("tr");
    fireEvent.click(coverageRow as HTMLTableRowElement);

    expect(await screen.findByText("Sensor detail — Wind_80m")).toBeTruthy();
    expect(screen.getByText("Weibull k")).toBeTruthy();
  });

  it("opens the cleaned CSV export URL for the active session", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    renderWithProviders(<DataPage />);

    await screen.findByText("45 min");
    fireEvent.click(screen.getByRole("button", { name: "Export Cleaned CSV" }));

    expect(window.open).toHaveBeenCalledWith("/api/sessions/session-1/exports/timeseries", "_blank", "noopener");
  });
});