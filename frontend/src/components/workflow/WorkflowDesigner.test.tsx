import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { datasetsApi, healthApi, sessionsApi, workflowApi } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { WorkflowDesigner } from "./WorkflowDesigner";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    healthApi: {
      ...actual.healthApi,
      get: vi.fn(),
    },
    sessionsApi: {
      ...actual.sessionsApi,
      create: vi.fn(),
      get: vi.fn(),
      reset: vi.fn(),
      remove: vi.fn(),
    },
    datasetsApi: {
      ...actual.datasetsApi,
      list: vi.fn(),
      create: vi.fn(),
      remove: vi.fn(),
      loadIntoSession: vi.fn(),
    },
    workflowApi: {
      ...actual.workflowApi,
      getCapabilities: vi.fn(),
      listSnapshots: vi.fn(),
    },
  };
});

class ResizeObserverMock {
  observe() {}

  unobserve() {}

  disconnect() {}
}

vi.stubGlobal("ResizeObserver", ResizeObserverMock);

function renderDesigner(initialEntry = "/overview") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <WorkflowDesigner />,
        children: [
          {
            path: "overview",
            element: <div>Overview outlet content</div>,
          },
        ],
      },
    ],
    { initialEntries: [initialEntry] },
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("WorkflowDesigner", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    useWorkspaceStore.getState().setSessionId("session-workflow");
    vi.mocked(healthApi.get).mockResolvedValue({
      status: "ok",
      service: "gokaatru-web-api",
    });
    vi.mocked(sessionsApi.get).mockResolvedValue({
      session_id: "session-workflow",
      workspace_dir: "data/sessions/session-workflow",
      created_at: "2026-04-07T00:00:00Z",
      updated_at: "2026-04-07T00:00:00Z",
      project_name: "North Ridge",
      measurement_type: "mast",
      hub_height_m: 150,
      timeseries_loaded: true,
      datamodel_loaded: true,
      era5_nodes_loaded: false,
      era5_interpolated_loaded: false,
      ltc_algorithms: [],
      completed_steps: ["timeseries", "datamodel", "config"],
    });
    vi.mocked(datasetsApi.list).mockResolvedValue({
      datasets: [
        {
          id: "dataset-1",
          name: "HornsRev-MAST",
          timeseries_file: "timeseries.csv",
          datamodel_file: "datamodel.json",
          uploaded_at: "2026-04-11T00:00:00Z",
          sensor_count: 5,
          date_range: { start: "2003-01-01T00:00:00", end: "2025-12-31T23:50:00" },
          coverage_summary: { Spd_100m: 94.2 },
          coverage_pct: 94.2,
        },
      ],
    });
    vi.mocked(workflowApi.getCapabilities).mockResolvedValue({
      capabilities: [
        {
          template_id: "apply_cleaning_rule",
          required_params: ["rule_type", "sensor", "params"],
          optional_params: ["start_date", "end_date"],
        },
      ],
    });
    vi.mocked(workflowApi.listSnapshots).mockResolvedValue({ snapshots: [] });
  });

  it("renders the workflow shell and nested route content", async () => {
    renderDesigner();

    expect(await screen.findByRole("heading", { name: "North Ridge" })).toBeTruthy();
    expect(screen.getByText("Overview outlet content")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Drag into canvas" })).toBeTruthy();
    expect(screen.getByText("Shared inputs")).toBeTruthy();
    expect(screen.getByText("Apply Cleaning Rule")).toBeTruthy();
    expect(screen.getByText("HornsRev-MAST")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Overview" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Data" })).toBeTruthy();
  });
});