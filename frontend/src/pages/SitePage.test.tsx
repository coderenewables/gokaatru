import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, configApi, resultsApi, uploadsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { SitePage } from "./SitePage";

vi.mock("../components/common/PlotlyFigure", () => ({
  PlotlyFigure: ({ plot, emptyTitle }: { plot?: { title?: string } | null; emptyTitle: string }) => (
    <div>{plot ? `plot:${plot.title}` : emptyTitle}</div>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
      getSummary: vi.fn(),
      update: vi.fn(),
    },
    uploadsApi: {
      ...actual.uploadsApi,
      getSensors: vi.fn(),
    },
    analysisApi: {
      ...actual.analysisApi,
      calculateShear: vi.fn(),
      buildShearTable: vi.fn(),
      calculateRoughness: vi.fn(),
      buildRoughnessTable: vi.fn(),
      extrapolateHub: vi.fn(),
    },
    resultsApi: {
      ...actual.resultsApi,
      getPlot: vi.fn(),
    },
  };
});

describe("SitePage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.mocked(configApi.get).mockResolvedValue({
      project_name: "North Ridge",
      measurement_type: "mast",
      location: {
        latitude: 12.34,
        longitude: 56.78,
        elevation_m: 111,
      },
      hub_height_m: 140,
    });
    vi.mocked(configApi.getSummary).mockResolvedValue({
      completed_steps: ["config"],
      project_name: "North Ridge",
      shear_table_ready: true,
      roughness_table_ready: true,
    });
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        { name: "Wind_100m", height_m: 100, sensor_type: "wind_speed", data_coverage_pct: 99, record_count: 1000 },
        { name: "Wind_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 98, record_count: 1000 },
        { name: "Dir_100m", height_m: 100, sensor_type: "wind_direction", data_coverage_pct: 99, record_count: 1000 },
      ],
    });
    vi.mocked(resultsApi.getPlot).mockImplementation(async (_sessionId, plotName, body) => ({
      title: `${plotName}:${JSON.stringify(body)}`,
      plotly_json: JSON.stringify({ data: [], layout: {}, config: {} }),
      png_base64: null,
    }));
    vi.mocked(configApi.update).mockResolvedValue({ status: "ok", runconfig: {}, file_path: "runconfig.json" });
    vi.mocked(analysisApi.calculateShear).mockResolvedValue({ status: "ok" });
    vi.mocked(analysisApi.buildShearTable).mockResolvedValue({ method: "shear", aggregation: "mean", table: [[1]] });
    vi.mocked(analysisApi.calculateRoughness).mockResolvedValue({ status: "ok" });
    vi.mocked(analysisApi.buildRoughnessTable).mockResolvedValue({ method: "roughness", aggregation: "mean", table: [[1]] });
    vi.mocked(analysisApi.extrapolateHub).mockImplementation(async (_sessionId, body) => ({
      status: "ok",
      column_name: `Wind_${String((body as { hub_height_m: number }).hub_height_m)}m`,
      method_counts: { direct: 10, interpolated: 20, extrapolated: 30 },
    }));
  });

  it("shows the empty state when no session exists", () => {
    renderWithProviders(<SitePage />);

    expect(screen.getByText("Session required")).toBeTruthy();
  });

  it("loads site metadata and renders heatmap placeholders", async () => {
    useWorkspaceStore.getState().setSessionId("session-site");
    renderWithProviders(<SitePage />);

    expect(await screen.findByDisplayValue("North Ridge")).toBeTruthy();
    expect(screen.getByDisplayValue("mast")).toBeTruthy();
    expect(screen.getByDisplayValue("12.34")).toBeTruthy();
    expect(screen.getByDisplayValue("56.78")).toBeTruthy();
    expect(screen.getByDisplayValue("111")).toBeTruthy();
    expect(await screen.findByText('plot:shear_table:{"table_type":"shear"}')).toBeTruthy();
    expect(screen.getByText('plot:shear_table:{"table_type":"roughness"}')).toBeTruthy();
  });

  it("repopulates metadata from runconfig when the stored draft is not dirty", async () => {
    useWorkspaceStore.getState().setSessionId("session-site");
    useWorkspaceStore.getState().patchFormDraft("site", {
      projectName: "",
      measurementType: "mast",
      latitude: "",
      longitude: "",
      elevation: "0",
      hubHeight: "",
      initialized: true,
      dirty: false,
    });

    renderWithProviders(<SitePage />);

    expect(await screen.findByDisplayValue("North Ridge")).toBeTruthy();
    expect(screen.getByDisplayValue("12.34")).toBeTruthy();
    expect(screen.getByDisplayValue("56.78")).toBeTruthy();
    expect(screen.getByDisplayValue("111")).toBeTruthy();
    expect(screen.getByDisplayValue("140")).toBeTruthy();
  });

  it("saves metadata and runs extrapolation", async () => {
    useWorkspaceStore.getState().setSessionId("session-site");
    renderWithProviders(<SitePage />);

    await screen.findByDisplayValue("North Ridge");
    fireEvent.change(screen.getByDisplayValue("North Ridge"), { target: { value: "South Ridge" } });
    fireEvent.change(screen.getByDisplayValue("140"), { target: { value: "150" } });

    fireEvent.click(screen.getByRole("button", { name: "Save Metadata" }));
    await waitFor(() => {
      expect(configApi.update).toHaveBeenCalledWith("session-site", {
        updates: [
          { key: "project_name", value: "South Ridge" },
          { key: "measurement_type", value: "mast" },
          { key: "location.latitude", value: 12.34 },
          { key: "location.longitude", value: 56.78 },
          { key: "location.elevation_m", value: 111 },
          { key: "hub_height_m", value: 150 },
        ],
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Extrapolate To Hub" }));
    await waitFor(() => {
      expect(analysisApi.extrapolateHub).toHaveBeenCalledWith("session-site", {
        hub_height_m: 150,
        shear_model: "power_law",
      });
    });

    expect((await screen.findAllByText("Wind_150m")).length).toBeGreaterThan(0);
  });
});