import { beforeEach, describe, expect, it, vi } from "vitest";

const { getPrefixHash, deleteSensors } = vi.hoisted(() => ({
  getPrefixHash: vi.fn(),
  deleteSensors: vi.fn(),
}));

vi.mock("../lib/sweepApi", async () => {
  const actual = await vi.importActual<typeof import("../lib/sweepApi")>("../lib/sweepApi");
  return { ...actual, getPrefixHash };
});

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, deleteSensors };
});

import { useWorkspaceStore } from "../store/useWorkspaceStore";
import type { SensorRow } from "../types/analysis";

const SENSORS: SensorRow[] = [
  { name: "Spd_80m", height_m: 80, sensor_type: "wind_speed", data_coverage_pct: 95, record_count: 1000 },
  { name: "Spd_120m", height_m: 120, sensor_type: "wind_speed", data_coverage_pct: 94, record_count: 1000 },
];

describe("loadPrefixHash", () => {
  beforeEach(() => {
    getPrefixHash.mockReset();
    deleteSensors.mockReset();
    useWorkspaceStore.setState({
      session: { session_id: "session-1" } as never,
      sensors: SENSORS,
      prefixHash: null,
      reanalysisSourcesForPrefix: [],
      cleaningActionsCount: 0,
    });
  });

  it("fetches the prefix hash and its two companion figures from the sweep prefix-hash route", async () => {
    getPrefixHash.mockResolvedValue({
      fixed_prefix_hash: "a3f19c2b1e0d4f77",
      reanalysis_sources: ["era5", "merra2"],
      cleaning_actions_count: 3,
    });

    await useWorkspaceStore.getState().loadPrefixHash();

    expect(getPrefixHash).toHaveBeenCalledWith(expect.any(String), "session-1");
    const state = useWorkspaceStore.getState();
    expect(state.prefixHash).toBe("a3f19c2b1e0d4f77");
    expect(state.reanalysisSourcesForPrefix).toEqual(["era5", "merra2"]);
    expect(state.cleaningActionsCount).toBe(3);
  });

  it("is a no-op when there is no session", async () => {
    useWorkspaceStore.setState({ session: null });
    await useWorkspaceStore.getState().loadPrefixHash();
    expect(getPrefixHash).not.toHaveBeenCalled();
  });

  it("swallows a failed fetch rather than throwing — the hash is a disclosure, not a gate", async () => {
    getPrefixHash.mockRejectedValue(new Error("network down"));
    await expect(useWorkspaceStore.getState().loadPrefixHash()).resolves.toBeUndefined();
    expect(useWorkspaceStore.getState().prefixHash).toBeNull();
  });

  it("re-fetches the prefix hash after a sensor is dropped, since dropping one changes it", async () => {
    getPrefixHash.mockResolvedValue({
      fixed_prefix_hash: "changed00000000",
      reanalysis_sources: ["era5"],
      cleaning_actions_count: 0,
    });
    deleteSensors.mockResolvedValue({ removed: ["Spd_80m"], remaining_count: 1 });

    await useWorkspaceStore.getState().deleteSensors(["Spd_80m"]);

    expect(getPrefixHash).toHaveBeenCalledTimes(1);
  });
});
