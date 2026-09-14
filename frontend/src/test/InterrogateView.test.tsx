// Interrogate phase (design doc: Interrogate) — Spread, Gates, Sensitivity and Summary
// as one scrolling report under a single metric switch. Composes SpreadSummaryView,
// SpreadExplorer, SensitivityView and GateReportView unchanged; nothing here re-derives
// their statistics (see sweepAnalysis.test.ts, and tests/test_sweep_analysis.py for the
// variance decomposition, which now lives server-side).
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { InterrogateView } from "../components/InterrogateView";
import { useSweepStore, spreadKey } from "../store/useSweepStore";
import type { AxisContribution, ScenarioRow, SweepManifest } from "../types/sweep";

function row(overrides: Partial<ScenarioRow> & { config_hash: string }): ScenarioRow {
  return {
    fixed_prefix_hash: "a3f19c2b1e0d4f77",
    status: "ok",
    admissible: true,
    failed_gates: "",
    warned_gates: "",
    marked_gates: "",
    error: null,
    shear_fit_policy: "nearest_2",
    reference_policy: "nearest_2",
    shear_model: "power_law_mean",
    reference_source: "era5",
    ltc_algorithm: "variance_ratio",
    long_term_mean_speed_mps: 8,
    gate_extrapolation_ratio: "pass",
    ...overrides,
  } as ScenarioRow;
}

const ROWS = [
  row({ config_hash: "a", long_term_mean_speed_mps: 7.9 }),
  row({ config_hash: "b", long_term_mean_speed_mps: 8.1 }),
  row({ config_hash: "c", long_term_mean_speed_mps: 8.3, reference_source: "merra2" }),
];

const MANIFEST = {
  sweep_id: "sweep-1",
  fixed_prefix_hash: "a3f19c2b1e0d4f77",
  counts: { planned: 3, run: 3, completed: 3, admissible: 3, excluded: 0, failed: 0 },
} as unknown as SweepManifest;

// The decomposition is computed server-side now, so the store holds it rather than
// deriving it on render. Seeded here under the key the views look it up by.
const CONTRIBUTIONS: AxisContribution[] = [
  {
    axis: "reference_source",
    levels: 2,
    share: 1,
    swing: 0.3,
    level_means: [
      { level: "merra2", mean: 8.3, count: 1 },
      { level: "era5", mean: 8.0, count: 2 },
    ],
  },
  { axis: "ltc_algorithm", levels: 1, share: 0, swing: 0, level_means: [] },
];

const HASHES = ROWS.map((entry) => entry.config_hash);

beforeEach(() => {
  useSweepStore.setState({
    rows: ROWS,
    manifest: MANIFEST,
    metric: "long_term_mean_speed_mps",
    filters: {},
    showInadmissible: true,
    selectedScenario: null,
    spread: {
      [spreadKey("sweep-1", "long_term_mean_speed_mps", HASHES)]: CONTRIBUTIONS,
      [spreadKey("sweep-1", "total_uncertainty_pct", HASHES)]: CONTRIBUTIONS,
    },
    spreadPending: {},
  } as never);
});

describe("InterrogateView", () => {
  it("renders the disclosure banner, headline spread, distribution, variance, gates and scenario sections together", () => {
    render(<InterrogateView />);
    // SpreadSummaryView — the "no recommendation" disclosure and headline tiles.
    expect(screen.getByText("This is a spread, not a recommendation")).toBeInTheDocument();
    expect(screen.getByText("Headline spread")).toBeInTheDocument();
    expect(screen.getByText("Uncertainty budget")).toBeInTheDocument();
    // SensitivityView — "which axis moved it".
    expect(screen.getByText("Where the spread comes from")).toBeInTheDocument();
    // GateReportView — the admissibility grid and could-not-run section survive the merge.
    expect(screen.getByText("Admissibility")).toBeInTheDocument();
    // SpreadSummaryView's own results table + export section.
    expect(screen.getByText("Take a scenario away")).toBeInTheDocument();
  });
});
