import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Routes, Route, MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { configApi, healthApi, sessionsApi } from "../lib/api";
import { OverviewPage } from "./OverviewPage";
import { useWorkspaceStore } from "../stores/workspaceStore";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    healthApi: {
      get: vi.fn(),
    },
    sessionsApi: {
      ...actual.sessionsApi,
      get: vi.fn(),
    },
    configApi: {
      ...actual.configApi,
      getSummary: vi.fn(),
    },
  };
});

function renderOverview(initialRoute = "/overview") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/overview" element={<OverviewPage />} />
          <Route path="/site" element={<div>Site page target</div>} />
          <Route path="/data" element={<div>Data page target</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OverviewPage", () => {
  beforeEach(() => {
    vi.mocked(healthApi.get).mockResolvedValue({ status: "ok", service: "gokaatru-api" });
    useWorkspaceStore.getState().resetWorkspace();
  });

  it("shows the empty state when no session exists", () => {
    renderOverview();

    expect(screen.getByText("No active session")).toBeTruthy();
    expect(screen.getByText("Create a session from the header to start the workflow.")).toBeTruthy();
  });

  it("navigates to the next incomplete route", async () => {
    useWorkspaceStore.getState().setSessionId("session-1");
    vi.mocked(sessionsApi.get).mockResolvedValue({
      session_id: "session-1",
      workspace_dir: "workspace/session-1",
      created_at: null,
      updated_at: null,
      project_name: "Test site",
      measurement_type: "mast",
      hub_height_m: 120,
      timeseries_loaded: true,
      datamodel_loaded: true,
      era5_nodes_loaded: false,
      era5_interpolated_loaded: false,
      ltc_algorithms: [],
      completed_steps: ["timeseries", "datamodel"],
    });
    vi.mocked(configApi.getSummary).mockResolvedValue({
      completed_steps: ["timeseries", "datamodel"],
      project_name: "Test site",
      timeseries_loaded: true,
      sensor_mapping_loaded: true,
      sensor_count: 3,
      avg_coverage_pct: 94.5,
      cleaning_rules_applied: 0,
      shear_table_ready: false,
      roughness_table_ready: false,
      era5_nodes_loaded: false,
      era5_data_sets_loaded: 0,
      era5_interpolated_ready: false,
      ltc_algorithms_run: [],
      ensemble_ready: false,
      scenario_count: 0,
      coordinate: null,
      hub_height_m: 120,
    });

    renderOverview();

    await screen.findByText("Test site");
    expect(screen.getByText("Project summary (/summary)")).toBeTruthy();
  expect(screen.getByText("Data quality scorecard")).toBeTruthy();
  expect(screen.getByText("94.5%")) .toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go To Next Step" }));

    await waitFor(() => {
      expect(screen.getByText("Site page target")).toBeTruthy();
    });
  });
});