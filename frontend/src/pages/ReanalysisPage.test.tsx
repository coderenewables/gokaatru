import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisApi, configApi, resultsApi, sessionsApi } from "../lib/api";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { renderWithProviders } from "../test/render";
import { ReanalysisPage } from "./ReanalysisPage";

vi.mock("../components/common/GeoJsonMap", () => ({
  GeoJsonMap: ({ featureCollection, emptyTitle }: { featureCollection?: { features?: unknown[] } | null; emptyTitle: string }) => (
    <div>{featureCollection ? `map:${featureCollection.features?.length ?? 0}` : emptyTitle}</div>
  ),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    sessionsApi: {
      ...actual.sessionsApi,
      get: vi.fn(),
    },
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
    analysisApi: {
      ...actual.analysisApi,
      findEra5Nodes: vi.fn(),
      extractEra5: vi.fn(),
      interpolateEra5: vi.fn(),
    },
    resultsApi: {
      ...actual.resultsApi,
      getSiteMap: vi.fn(),
    },
  };
});

describe("ReanalysisPage", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    vi.mocked(sessionsApi.get).mockResolvedValue({
      session_id: "session-reanalysis",
      workspace_dir: "workspace",
      created_at: null,
      updated_at: null,
      project_name: "North Ridge",
      measurement_type: "mast",
      hub_height_m: 140,
      timeseries_loaded: true,
      datamodel_loaded: true,
      era5_nodes_loaded: true,
      era5_interpolated_loaded: false,
      ltc_algorithms: [],
      completed_steps: ["timeseries", "datamodel", "era5_nodes"],
    });
    vi.mocked(configApi.get).mockResolvedValue({
      location: {
        latitude: 11.11,
        longitude: 22.22,
      },
    });
    vi.mocked(resultsApi.getSiteMap).mockResolvedValue({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [22.22, 11.11] },
          properties: { type: "mast" },
        },
      ],
    });
    vi.mocked(analysisApi.findEra5Nodes).mockResolvedValue({
      nodes: [
        { latitude: 11.25, longitude: 22.35, distance_km: 18.2, bearing: "NE" },
      ],
      grid_resolution_deg: 0.25,
    });
    vi.mocked(analysisApi.extractEra5).mockResolvedValue({
      status: "ok",
      latitude: 11.25,
      longitude: 22.35,
      rows: 100,
      start: "2000-01-01",
      end: "2025-12-31",
      variables: ["u10", "v10"],
      cached: true,
    });
    vi.mocked(analysisApi.interpolateEra5).mockResolvedValue({
      status: "ok",
      rows: 100,
      method: "idw",
      variables: ["u10", "v10"],
    });
  });

  it("shows the empty state when no session exists", () => {
    renderWithProviders(<ReanalysisPage />);

    expect(screen.getByText("Session required")).toBeTruthy();
  });

  it("prefills coordinates and renders the persisted map", async () => {
    useWorkspaceStore.getState().setSessionId("session-reanalysis");
    renderWithProviders(<ReanalysisPage />);

    expect(await screen.findByDisplayValue("11.11")).toBeTruthy();
    expect(screen.getByDisplayValue("22.22")).toBeTruthy();
    expect(screen.getByText("map:1")).toBeTruthy();
  });

  it("finds nodes, extracts all node datasets, and interpolates the site", async () => {
    useWorkspaceStore.getState().setSessionId("session-reanalysis");
    renderWithProviders(<ReanalysisPage />);

    await screen.findByDisplayValue("11.11");
    fireEvent.click(screen.getByRole("button", { name: "Find ERA5 Nodes" }));

    await waitFor(() => {
      expect(analysisApi.findEra5Nodes).toHaveBeenCalledWith("session-reanalysis", {
        latitude: 11.11,
        longitude: 22.22,
      });
    });

    expect(await screen.findByText("18.2 km")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Extract All Nodes" }));
    await waitFor(() => {
      expect(analysisApi.extractEra5).toHaveBeenCalledWith("session-reanalysis", {
        latitude: 11.25,
        longitude: 22.35,
        start_date: "2000-01-01",
        end_date: "2025-12-31",
      });
    });

    expect(await screen.findByText("u10, v10")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Interpolate Site" }));
    await waitFor(() => {
      expect(analysisApi.interpolateEra5).toHaveBeenCalledWith("session-reanalysis");
    });
  });
});