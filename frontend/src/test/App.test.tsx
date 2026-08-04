import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

// Mock react-plotly.js so the full App shell (which can reach PlotFrame via
// stage views) doesn't load real Plotly in jsdom.
vi.mock("react-plotly.js", () => ({
  default: ({ layout }: { layout?: { title?: string } }) => (
    <div data-testid="plotly-stub">{String(layout?.title ?? "")}</div>
  ),
}));

// Mock the API module before App/store import so bootstrapSession is deterministic.
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    createSession: vi.fn(async () => ({ status: "ok", session_id: "test-session-1234" })),
    getSessionSummary: vi.fn(async () => ({
      session_id: "test-session-1234",
      workspace_dir: null,
      created_at: null,
      updated_at: null,
      project_name: "Test Site",
      measurement_type: "mast",
      hub_height_m: 120,
      timeseries_loaded: false,
      datamodel_loaded: false,
      era5_nodes_loaded: false,
      era5_interpolated_loaded: false,
      ltc_algorithms: [],
      completed_steps: [],
    })),
    getAnalysisSummary: vi.fn(async () => ({ completed_steps: [] })),
    getSessionConfig: vi.fn(async () => ({})),
    getSensors: vi.fn(async () => ({ sensors: [] })),
    getWorkflowCapabilities: vi.fn(async () => ({ capabilities: [] })),
    listScenarios: vi.fn(async () => ({ scenarios: [] })),
    getApiHealth: vi.fn(async () => ({ status: "ok", service: "gokaatru-web-api" })),
  };
});

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import App from "../App";

function resetStore() {
  useWorkspaceStore.setState({
    session: null,
    sessionStatus: "idle",
    sessionError: null,
    busyLabel: null,
    activity: [],
    summary: null,
  });
  if (typeof window !== "undefined") {
    window.localStorage.clear();
  }
}

describe("App bootable shell", () => {
  beforeEach(() => {
    resetStore();
  });

  it("renders the home view before a session exists", () => {
    render(<App />);
    expect(screen.getByText("GoKaatru")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start workspace/i })).toBeInTheDocument();
  });

  it("bootstraps a session and renders the workspace shell", async () => {
    render(<App />);
    const startButton = screen.getByRole("button", { name: /start workspace/i });

    await act(async () => {
      startButton.click();
    });

    await waitFor(() => {
      // The workspace opens at the standalone data import view.
      expect(screen.getByRole("button", { name: "Data import" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Stepper" })).toBeInTheDocument();
      expect(screen.getByText("Site & hub height")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Data loading" })).not.toBeInTheDocument();
  });
});
