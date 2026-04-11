import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { healthApi, sessionsApi } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { AppShell } from "./AppShell";

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
  };
});

function renderShell(initialEntry = "/overview") {
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
        element: <AppShell />,
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

describe("AppShell", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    useWorkspaceStore.getState().setSessionId("session-shell");
    vi.mocked(healthApi.get).mockResolvedValue({
      status: "ok",
      service: "gokaatru-web-api",
    });
    vi.mocked(sessionsApi.get).mockResolvedValue({
      session_id: "session-shell",
      workspace_dir: "data/sessions/session-shell",
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
  });

  it("renders the step navigation and nested outlet content", async () => {
    renderShell();

    expect(await screen.findByRole("heading", { name: "North Ridge" })).toBeTruthy();
    expect(screen.getByText("Overview outlet content")).toBeTruthy();
    expect(screen.getByText("Manage the workflow, inspect session state, and continue the next analysis step.")).toBeTruthy();
    expect(screen.queryByText(/Phase 6\.7 turns the scaffold/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Edit Metadata" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Overview/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Data/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Vertical Extrapolation/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Reanalysis/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /LTC/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Results/ })).toBeTruthy();
    expect(screen.getByText("session-shell")).toBeTruthy();
  });
});