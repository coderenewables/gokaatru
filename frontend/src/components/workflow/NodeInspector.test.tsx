import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configApi, uploadsApi, workflowApi } from "../../lib/api";
import { type WorkflowNode, useWorkflowStore } from "../../stores/workflowStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { renderWithProviders } from "../../test/render";
import { NodeInspector } from "./NodeInspector";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      update: vi.fn(),
    },
    workflowApi: {
      ...actual.workflowApi,
      getCapabilities: vi.fn(),
    },
    uploadsApi: {
      ...actual.uploadsApi,
      getSensors: vi.fn(),
    },
  };
});

function buildOperationNode(paramsJson: string): WorkflowNode {
  return {
    id: "op-1",
    type: "operationNode",
    position: { x: 120, y: 320 },
    data: {
      kind: "operation",
      label: "Apply Cleaning Rule",
      description: "Apply a cleaning rule to a selected sensor.",
      category: "Data Cleaning",
      status: "idle",
      stale: false,
      branchColor: "#0b7a6f",
      templateId: "apply_cleaning_rule",
      summary: "1 configurable field",
      fields: [
        {
          key: "params_json",
          label: "Parameters JSON",
          type: "text",
          defaultValue: "{}",
          placeholder: '{"key":"value"}',
        },
      ],
      config: {
        params_json: paramsJson,
      },
    },
  };
}

function seedWorkflowStore(node: WorkflowNode) {
  useWorkflowStore.setState({
    branches: [{ id: "main", name: "main", color: "#0b7a6f", sessionId: "session-inspector", forkPoint: null }],
    activeBranchId: "main",
    branchStates: {
      main: {
        nodes: [node],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      },
    },
    historyPast: { main: [] },
    historyFuture: { main: [] },
    selectedNodeId: node.id,
    executionEvents: [],
    executionError: null,
  });
}

describe("NodeInspector", () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetWorkspace();
    useWorkspaceStore.getState().setSessionId("session-inspector");
    vi.mocked(workflowApi.getCapabilities).mockResolvedValue({
      capabilities: [
        {
          template_id: "apply_cleaning_rule",
          required_params: ["rule_type", "sensor", "params"],
          optional_params: ["start_date", "end_date"],
        },
      ],
    });
    vi.mocked(uploadsApi.getSensors).mockResolvedValue({
      sensors: [
        {
          name: "Spd_100m",
          height_m: 100,
          sensor_type: "wind_speed",
          data_coverage_pct: 99.4,
          record_count: 4321,
        },
      ],
    });
    vi.mocked(configApi.update).mockResolvedValue({
      status: "ok",
      runconfig: {},
      file_path: "runconfig.json",
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("seeds untouched params_json with sample values and persists them to runconfig", async () => {
    seedWorkflowStore(buildOperationNode("{}"));

    renderWithProviders(<NodeInspector />);

    await screen.findByRole("heading", { name: "Apply Cleaning Rule" });

    await waitFor(() => {
      expect(useWorkflowStore.getState().branchStates.main.nodes[0]?.data.config?.params_json).toContain('"rule_type"');
    });

    const ruleTypeField = screen.getByDisplayValue("example_rule_type") as HTMLInputElement;
    expect(ruleTypeField.value).toBe("example_rule_type");

    const sensorField = screen.getByRole("combobox", { name: /sensor/i }) as HTMLSelectElement;
    expect(sensorField.value).toBe("Spd_100m");

    const paramsField = screen.getByDisplayValue(/example_key/) as HTMLTextAreaElement;
    expect(paramsField.value).toContain('"example_key": "value"');

    await waitFor(() => {
      expect(configApi.update).toHaveBeenCalledWith("session-inspector", {
        updates: [
          {
            key: "workflow.branches.main.nodes.op-1",
            value: expect.objectContaining({
              template_id: "apply_cleaning_rule",
              label: "Apply Cleaning Rule",
              config: expect.objectContaining({
                params_json: expect.stringContaining('"rule_type"'),
              }),
            }),
          },
        ],
      });
    }, { timeout: 1500 });
  });

  it("keeps an existing params_json draft unchanged when capability hints load", async () => {
    seedWorkflowStore(buildOperationNode('{"custom":true}'));

    renderWithProviders(<NodeInspector />);

    await screen.findByRole("heading", { name: "Apply Cleaning Rule" });

    expect(useWorkflowStore.getState().branchStates.main.nodes[0]?.data.config?.params_json).toBe('{"custom":true}');
    await waitFor(() => {
      expect(configApi.update).toHaveBeenCalledWith("session-inspector", {
        updates: [
          {
            key: "workflow.branches.main.nodes.op-1",
            value: expect.objectContaining({
              config: expect.objectContaining({
                params_json: '{"custom":true}',
              }),
            }),
          },
        ],
      });
    }, { timeout: 1500 });
  });
});