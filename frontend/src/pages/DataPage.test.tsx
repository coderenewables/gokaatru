import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { DataPage } from "./DataPage";

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
    },
  };
});

describe("DataPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
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
});