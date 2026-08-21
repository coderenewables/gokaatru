// The sweep run lifecycle — the seam where a finished run becomes a visible spread.
//
// Results are persisted server-side and fetched by id; the store never receives them on
// the stream. So two things have to hold, and neither is covered by the selection tests:
// a completed run must load its table, and a reload must recover the last one from the
// session rather than showing an empty state over a sweep that exists on disk.
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScenarioRow, SweepManifest, SweepSummary } from "../types/sweep";

const getSweep = vi.fn();
const listSweeps = vi.fn();
const streamSweep = vi.fn();

vi.mock("../lib/sweepApi", () => ({
  getSweep: (...args: unknown[]) => getSweep(...args),
  listSweeps: (...args: unknown[]) => listSweeps(...args),
  streamSweep: (...args: unknown[]) => streamSweep(...args),
  estimateSweep: vi.fn(),
  getSweepAxes: vi.fn(),
  getScenarioRunconfig: vi.fn(),
}));

const { useSweepStore } = await import("../store/useSweepStore");

const MANIFEST = { sweep_id: "sweep-1", counts: { run: 1, admissible: 1 } } as unknown as SweepManifest;
const ROWS = [
  { config_hash: "a", status: "ok", admissible: true, long_term_mean_speed_mps: 8.1 },
] as unknown as ScenarioRow[];
const SUMMARY = [{ sweep_id: "sweep-1", counts: { admissible: 1, completed: 1 } }] as unknown as SweepSummary[];

describe("sweep run lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSweepStore.setState({ phase: "idle", rows: [], manifest: null, sweeps: [], error: null });
  });

  it("loads the persisted table once the stream hands back a manifest", async () => {
    // The stream carries progress, not results. The manifest is the only route from a
    // finished run to the rows, so dropping it strands a completed sweep on disk.
    streamSweep.mockResolvedValue(MANIFEST);
    getSweep.mockResolvedValue({ manifest: MANIFEST, results: ROWS });
    listSweeps.mockResolvedValue(SUMMARY);

    await useSweepStore.getState().start("http://api", "session-1");

    expect(getSweep).toHaveBeenCalledWith("http://api", "session-1", "sweep-1");
    expect(useSweepStore.getState().phase).toBe("complete");
    expect(useSweepStore.getState().rows).toHaveLength(1);
  });

  it("reports the run as complete-but-empty when no manifest arrived", async () => {
    // Degraded rather than silent: the phase still settles, but nothing claims to have
    // rows it does not have.
    streamSweep.mockResolvedValue(null);

    await useSweepStore.getState().start("http://api", "session-1");

    expect(getSweep).not.toHaveBeenCalled();
    expect(useSweepStore.getState().rows).toEqual([]);
  });

  it("opens a saved sweep into the same shape a live run produces", async () => {
    getSweep.mockResolvedValue({ manifest: MANIFEST, results: ROWS });

    await useSweepStore.getState().openSweep("http://api", "session-1", "sweep-1");

    const state = useSweepStore.getState();
    expect(state.phase).toBe("complete");
    expect(state.rows).toHaveLength(1);
    expect(state.manifest?.sweep_id).toBe("sweep-1");
  });

  it("surfaces a failure to open rather than leaving a stale table", async () => {
    useSweepStore.setState({ rows: ROWS, phase: "complete" });
    getSweep.mockRejectedValue(new Error("Sweep 'gone' is not available"));

    await useSweepStore.getState().openSweep("http://api", "session-1", "gone");

    expect(useSweepStore.getState().phase).toBe("error");
    expect(useSweepStore.getState().error).toContain("not available");
  });
});

describe("gate chips on a result row", () => {
  it("does not treat a measured value column as a gate", async () => {
    // `gate_<name>_value` sits beside `gate_<name>`. A naive `gate_` prefix match turns
    // every value column into a phantom chip, and because a number is neither "pass" nor
    // "not_applicable" it survives the filter that keeps the column sparse.
    const { summariseGates } = await import("../lib/sweepAnalysis");
    const row = {
      config_hash: "a",
      status: "ok",
      admissible: true,
      gate_extrapolation_ratio: "warn",
      gate_extrapolation_ratio_value: 2.0,
    } as unknown as ScenarioRow;

    const names = Object.keys(row)
      .filter((key) => key.startsWith("gate_") && !key.endsWith("_value"))
      .map((key) => key.slice("gate_".length));

    expect(names).toEqual(["extrapolation_ratio"]);
    expect(summariseGates([row]).map((entry) => entry.gate)).toEqual(["extrapolation_ratio"]);
  });
});
