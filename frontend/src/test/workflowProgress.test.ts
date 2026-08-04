import { describe, expect, it } from "vitest";

import { getWorkflowProgress } from "../components/WorkflowView";
import { createDefaultWindAnalysisConfig } from "../lib/defaultConfig";
import { createWorkflowGraph } from "../lib/workflow";
import type { WorkflowExecutionStatusResponse } from "../types/analysis";

describe("getWorkflowProgress", () => {
  it("reports completed node duration, elapsed runtime, and estimated remaining time", () => {
    const config = createDefaultWindAnalysisConfig();
    config.site.hubHeightM = 150;
    const { nodes } = createWorkflowGraph(config, []);
    const status: WorkflowExecutionStatusResponse = {
      run_id: "run-1",
      is_running: true,
      cancelled: false,
      node_statuses: { dataset: "done", explore: "running" },
      events: [
        { run_id: "run-1", event_type: "run_started", timestamp: "2026-08-04T20:00:00.000Z" },
        { run_id: "run-1", event_type: "node_started", node_id: "dataset", status: "running", timestamp: "2026-08-04T20:00:01.000Z" },
        { run_id: "run-1", event_type: "node_finished", node_id: "dataset", status: "done", timestamp: "2026-08-04T20:00:06.000Z" },
        { run_id: "run-1", event_type: "node_started", node_id: "explore", status: "running", timestamp: "2026-08-04T20:00:07.000Z" },
      ],
    };

    const progress = getWorkflowProgress(nodes, status, Date.parse("2026-08-04T20:00:10.000Z"));

    expect(progress.completed).toBe(1);
    expect(progress.elapsedMs).toBe(10_000);
    expect(progress.nodeDurations.dataset).toBe(5_000);
    expect(progress.nodeDurations.explore).toBe(3_000);
    expect(progress.etaMs).toBeGreaterThan(0);
  });
});