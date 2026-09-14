// Canvas's "Load from sweep" action (design doc: "used only to load a config from the
// sweeps and run"). Pure sequencing of existing, already-tested machinery: fetch one
// scenario's materialised runconfig, replace the session's active config with it, then
// rebuild the DAG from the authoritative saved config — no new persistence/graph logic.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getScenarioRunconfig } = vi.hoisted(() => ({
  getScenarioRunconfig: vi.fn(),
}));

vi.mock("../lib/sweepApi", async () => {
  const actual = await vi.importActual<typeof import("../lib/sweepApi")>("../lib/sweepApi");
  return { ...actual, getScenarioRunconfig };
});

import { useWorkspaceStore } from "../store/useWorkspaceStore";

describe("loadScenarioIntoCanvas", () => {
  beforeEach(() => {
    getScenarioRunconfig.mockReset();
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      replaceWorkflowRunConfig: vi.fn().mockResolvedValue(true),
      rebuildWorkflowGraph: vi.fn().mockResolvedValue(undefined),
    });
  });

  it("fetches the scenario runconfig, replaces the active config, then rebuilds the graph", async () => {
    const scenarioConfig = { site: { hubHeightM: 150 }, scenario: { config_hash: "c1" } };
    getScenarioRunconfig.mockResolvedValue(scenarioConfig);

    await useWorkspaceStore.getState().loadScenarioIntoCanvas("sweep-1", "c1");

    expect(getScenarioRunconfig).toHaveBeenCalledWith(expect.any(String), "session-1", "sweep-1", "c1");
    const state = useWorkspaceStore.getState();
    expect(state.replaceWorkflowRunConfig).toHaveBeenCalledWith(scenarioConfig);
    expect(state.rebuildWorkflowGraph).toHaveBeenCalledOnce();
  });

  it("does not rebuild the graph when saving the replaced config fails", async () => {
    getScenarioRunconfig.mockResolvedValue({ site: {} });
    useWorkspaceStore.setState({ replaceWorkflowRunConfig: vi.fn().mockResolvedValue(false) });

    await useWorkspaceStore.getState().loadScenarioIntoCanvas("sweep-1", "c1");

    expect(useWorkspaceStore.getState().rebuildWorkflowGraph).not.toHaveBeenCalled();
  });

  it("is a no-op when there is no session", async () => {
    useWorkspaceStore.setState({ session: null });
    await useWorkspaceStore.getState().loadScenarioIntoCanvas("sweep-1", "c1");
    expect(getScenarioRunconfig).not.toHaveBeenCalled();
  });

  it("logs a failure to the activity feed rather than throwing when the fetch fails", async () => {
    getScenarioRunconfig.mockRejectedValue(new Error("network down"));

    await expect(
      useWorkspaceStore.getState().loadScenarioIntoCanvas("sweep-1", "c1"),
    ).resolves.toBeUndefined();

    const activity = useWorkspaceStore.getState().activity;
    expect(activity[0]?.label).toMatch(/load scenario failed/i);
  });
});
