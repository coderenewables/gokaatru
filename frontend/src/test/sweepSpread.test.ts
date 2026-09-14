// The variance decomposition moved from the browser into the server.
//
// It used to live only in `lib/sweepAnalysis.ts`, so the question the Analysis Engine
// exists to answer — which methodological choice actually moved the number — was
// computable only inside the Interrogate page. The Copilot had no way to reach it and,
// asked about a spread, invented an explanation. The server now owns the statistic and
// the TypeScript copy is gone: two implementations of the same number drift, and this
// one drifts invisibly because both answers look plausible.
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AxisContribution, ScenarioRow, SweepManifest } from "../types/sweep";

const getSweepSpread = vi.fn();

vi.mock("../lib/sweepApi", () => ({
  getSweep: vi.fn(),
  listSweeps: vi.fn(),
  streamSweep: vi.fn(),
  estimateSweep: vi.fn(),
  getSweepAxes: vi.fn(),
  getScenarioRunconfig: vi.fn(),
  getSweepSpread: (...args: unknown[]) => getSweepSpread(...args),
}));

const { useSweepStore, spreadKey } = await import("../store/useSweepStore");
const sweepAnalysis = await import("../lib/sweepAnalysis");

const MANIFEST = { sweep_id: "sweep-1" } as unknown as SweepManifest;
const ROWS = [
  { config_hash: "a", status: "ok", admissible: true, long_term_mean_speed_mps: 8 },
  { config_hash: "b", status: "ok", admissible: true, long_term_mean_speed_mps: 10 },
] as unknown as ScenarioRow[];

const CONTRIBUTIONS: AxisContribution[] = [
  {
    axis: "ltc_algorithm",
    levels: 2,
    share: 1,
    swing: 2,
    level_means: [
      { level: "linear_least_squares", mean: 10, count: 1 },
      { level: "variance_ratio", mean: 8, count: 1 },
    ],
  },
  { axis: "shear_fit_policy", levels: 1, share: 0, swing: 0, level_means: [] },
];

describe("the client no longer computes the decomposition", () => {
  it("does not export decomposeVariance any more", () => {
    // A regression guard: a second implementation reappearing here is exactly the drift
    // deleting it was meant to prevent.
    expect("decomposeVariance" in sweepAnalysis).toBe(false);
  });

  it("still owns the row filtering the server deliberately does not duplicate", () => {
    expect(typeof sweepAnalysis.filterRows).toBe("function");
    expect(typeof sweepAnalysis.admissibleRows).toBe("function");
  });
});

describe("loadSpread", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSweepStore.setState({
      manifest: MANIFEST,
      rows: ROWS,
      spread: {},
      spreadPending: {},
    } as never);
  });

  it("fetches the decomposition for a metric and caches it under its key", async () => {
    getSweepSpread.mockResolvedValue({ contributions: CONTRIBUTIONS, scenarios_analysed: 2 });

    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a", "b"]);

    const key = spreadKey("sweep-1", "long_term_mean_speed_mps", ["a", "b"]);
    expect(useSweepStore.getState().spread[key]).toEqual(CONTRIBUTIONS);
    expect(getSweepSpread).toHaveBeenCalledTimes(1);
  });

  it("sends the caller's own row selection, so client-side filters are honoured", async () => {
    getSweepSpread.mockResolvedValue({ contributions: CONTRIBUTIONS });

    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a"]);

    const [, , sweepId, payload] = getSweepSpread.mock.calls[0] as unknown[];
    expect(sweepId).toBe("sweep-1");
    expect(payload).toMatchObject({
      metric: "long_term_mean_speed_mps",
      config_hashes: ["a"],
    });
  });

  it("does not refetch a key it already holds", async () => {
    getSweepSpread.mockResolvedValue({ contributions: CONTRIBUTIONS });

    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a", "b"]);
    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a", "b"]);

    expect(getSweepSpread).toHaveBeenCalledTimes(1);
  });

  it("keys separately per metric, because the summary decomposes two of them", async () => {
    getSweepSpread.mockResolvedValue({ contributions: CONTRIBUTIONS });

    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a"]);
    await useSweepStore.getState().loadSpread("http://api", "s1", "total_uncertainty_pct", ["a"]);

    expect(getSweepSpread).toHaveBeenCalledTimes(2);
  });

  it("does nothing without a loaded sweep rather than calling with an empty id", async () => {
    useSweepStore.setState({ manifest: null } as never);
    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a"]);
    expect(getSweepSpread).not.toHaveBeenCalled();
  });

  it("records the failure and leaves the cache empty when the request fails", async () => {
    getSweepSpread.mockRejectedValue(new Error("upstream down"));

    await useSweepStore.getState().loadSpread("http://api", "s1", "long_term_mean_speed_mps", ["a"]);

    const key = spreadKey("sweep-1", "long_term_mean_speed_mps", ["a"]);
    expect(useSweepStore.getState().spread[key]).toBeUndefined();
    expect(useSweepStore.getState().spreadPending[key]).toBeFalsy();
  });
});
