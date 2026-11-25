import { afterEach, describe, expect, it } from "vitest";

import { SWEEP_PRESETS, toRequestBody, retainAvailableSelection, type SweepSelection } from "../store/useSweepStore";
import {
  DEFAULT_DESIGN,
  PRESETS,
  designFromSpec,
  emptyAxes,
  requestBody,
  requiresAnalystShear,
  retainAvailable,
  type SweepAxes,
  type SweepDesign,
} from "../workbench/run/design";
import { IDLE_RUN, LOG_LIMIT, STARTED_RUN, parseFrames, reduceRun, type ProgressEvent } from "../workbench/run/progress";
import { useDesign } from "../workbench/run/store";

const level = (name: string, available = true, extra: object = {}) => ({ name, available, ...extra });

// A lidar-like campaign: no boom redundancy, one policy that resolves to a single height, no MERRA-2.
const AXES: SweepAxes = {
  sensor_policies: [
    level("nearest_2"),
    level("availability_90"),
    level("redundant_boom", false, { reason: "No boom pair at any height." }),
    level("widest_lever", true, { can_fit_shear: false }),
  ],
  shear_models: [level("power_law_mean"), level("power_law_median"), level("power_law_momm"), level("power_law_constant"), level("log_law_mean", false, { reason: "Needs a roughness length." })],
  reference_sources: [level("era5"), level("merra2", false, { reason: "No MERRA-2 series interpolated." })],
};

const asSelection = (design: SweepDesign): SweepSelection => ({
  shearFitPolicies: design.shear_fit_policies,
  referencePolicies: design.reference_policies,
  shearModels: design.shear_models,
  referenceSources: design.reference_sources,
  ltcAlgorithms: design.ltc_algorithms,
  analystShearAlpha: design.analyst_shear_alpha,
  thresholds: {},
});

describe("the presets and what the campaign can run", () => {
  afterEach(() => useDesign.getState().reset());

  it("carries the old interface's three presets, level for level", () => {
    expect(Object.keys(PRESETS)).toEqual(Object.keys(SWEEP_PRESETS));
    for (const name of Object.keys(PRESETS)) {
      const old = SWEEP_PRESETS[name];
      const next = PRESETS[name];
      expect(next.shear_fit_policies).toEqual(old.shearFitPolicies);
      expect(next.reference_policies).toEqual(old.referencePolicies);
      expect(next.shear_models).toEqual(old.shearModels);
      expect(next.reference_sources).toEqual(old.referenceSources);
      expect(next.ltc_algorithms).toEqual(old.ltcAlgorithms);
    }
  });

  it("drops the levels a preset names that the campaign cannot run, and names them", () => {
    useDesign.getState().applyPreset("Exhaustive", AXES);
    const { design, dropped } = useDesign.getState();
    expect(design.shear_fit_policies).toEqual(["nearest_2", "availability_90", "widest_lever"]);
    expect(design.reference_policies).toEqual(["nearest_2", "availability_90", "widest_lever"]);
    expect(design.shear_models).not.toContain("log_law_mean");
    expect(design.reference_sources).toEqual(["era5"]);
    expect(design.ltc_algorithms).toHaveLength(5);
    expect([...dropped].sort()).toEqual(["log_law_mean", "merra2", "redundant_boom"]);
  });

  it("intersects exactly as the old store does", () => {
    for (const name of Object.keys(PRESETS)) {
      const ours = retainAvailable({ ...DEFAULT_DESIGN, ...PRESETS[name] }, AXES);
      const theirs = retainAvailableSelection({ ...asSelection(DEFAULT_DESIGN), ...SWEEP_PRESETS[name] }, AXES as never);
      expect(ours.dropped).toEqual(theirs.dropped);
      expect(ours.design.shear_fit_policies).toEqual(theirs.selection.shearFitPolicies);
      expect(ours.design.reference_sources).toEqual(theirs.selection.referenceSources);
      expect(ours.design.shear_models).toEqual(theirs.selection.shearModels);
    }
  });

  it("asks for an exponent when a ticked policy resolves to one height", () => {
    expect(requiresAnalystShear({ ...DEFAULT_DESIGN }, AXES)).toBe(false);
    expect(requiresAnalystShear({ ...DEFAULT_DESIGN, shear_fit_policies: ["widest_lever"] }, AXES)).toBe(true);
  });

  it("reports an axis with nothing ticked", () => {
    expect(emptyAxes({ ...DEFAULT_DESIGN, shear_models: [] })).toEqual(["shear_models"]);
  });

  it("takes a whole design from a request-shaped spec, and checks it against the campaign on retain", () => {
    useDesign.getState().setDesign({ ...requestBody(DEFAULT_DESIGN), reference_sources: ["merra2"], hub_height_m: 120 });
    expect(useDesign.getState().design.hub_height_m).toBe(120);
    useDesign.getState().retain(AXES);
    expect(useDesign.getState().design.reference_sources).toEqual([]);
    expect(useDesign.getState().dropped).toEqual(["merra2"]);
    expect(designFromSpec({ ltc_algorithms: ["speedsort"] }).ltc_algorithms).toEqual(["speedsort"]);
  });
});

describe("the request the new designer sends", () => {
  it("equals the old interface's request for the same selection, for every preset", () => {
    for (const name of Object.keys(PRESETS)) {
      const { design } = retainAvailable({ ...DEFAULT_DESIGN, ...PRESETS[name] }, AXES);
      expect(requestBody(design)).toEqual(toRequestBody(asSelection(design)));
    }
    const withAlpha = { ...DEFAULT_DESIGN, analyst_shear_alpha: 0.2 };
    expect(requestBody(withAlpha)).toEqual(toRequestBody(asSelection(withAlpha)));
  });

  it("sends a hub height only when one was entered", () => {
    expect("hub_height_m" in requestBody(DEFAULT_DESIGN)).toBe(false);
    expect(requestBody({ ...DEFAULT_DESIGN, hub_height_m: 120 }).hub_height_m).toBe(120);
  });
});

describe("the run's event stream", () => {
  const events: ProgressEvent[] = [
    { event: "sweep_started", completed: 0, total: 4 },
    { event: "prefix_started", completed: 0, total: 4, detail: { shear_prefix: ["nearest_2", "power_law_mean", null] } },
    { event: "prefix_completed", completed: 0, total: 4, detail: { shear_prefix: ["nearest_2", "power_law_mean", null] } },
    { event: "scenario_completed", completed: 1, total: 4, config_hash: "aaaaaaaabbbb", detail: { admissible: true } },
    { event: "scenario_completed", completed: 2, total: 4, config_hash: "ccccccccdddd", detail: { admissible: false } },
    { event: "scenario_failed", completed: 3, total: 4, config_hash: "eeeeeeeeffff", error: "no overlap" },
    {
      event: "scenario_skipped_duplicate",
      completed: 4,
      total: 4,
      detail: { shear_fit_policy: "a", reference_policy: "b", same_as: "aaaaaaaabbbb" },
    },
  ];
  const fold = (list: ProgressEvent[]) => list.reduce(reduceRun, STARTED_RUN);

  it("counts scenarios by outcome and the shear tables built", () => {
    const state = fold(events);
    expect(state.phase).toBe("running");
    expect(state.completed).toBe(4);
    expect(state.total).toBe(4);
    expect(state.scenarios).toEqual({ ok: 1, inadmissible: 1, failed: 1, duplicates: 1 });
    expect(state.prefixes).toEqual({ started: 1, completed: 1 });
    expect(state.log.map((line) => line.kind)).toEqual([
      "prefix_started",
      "prefix_completed",
      "scenario_completed",
      "scenario_completed",
      "scenario_failed",
      "scenario_skipped_duplicate",
    ]);
    expect(state.log.at(-2)?.text).toBe("Scenario eeeeeeee failed: no overlap");
    expect(state.log.at(-1)?.text).toBe("Skipped a / b: it repeats aaaaaaaa");
  });

  it("ends with the manifest on sweep_finished, and with the reason on sweep_error", () => {
    const manifest = { sweep_id: "sw-1", not_swept_statement: "Not swept: wind direction." };
    const done = fold([...events, { event: "sweep_finished", completed: 4, total: 4, manifest }]);
    expect(done.phase).toBe("finished");
    expect(done.manifest).toEqual(manifest);
    const failed = fold([events[0], { event: "sweep_error", error: "RuntimeError('boom')" }]);
    expect(failed.phase).toBe("error");
    expect(failed.error).toBe("RuntimeError('boom')");
    expect(IDLE_RUN.phase).toBe("idle");
  });

  it("keeps only the newest events", () => {
    const many = Array.from({ length: LOG_LIMIT + 50 }, (_, i): ProgressEvent => ({ event: "scenario_completed", completed: i + 1, total: 1000, config_hash: `h${i}`, detail: { admissible: true } }));
    const state = fold(many);
    expect(state.log).toHaveLength(LOG_LIMIT);
    expect(state.scenarios.ok).toBe(LOG_LIMIT + 50);
  });

  it("reads frames from chunks that split them, and skips a malformed one", () => {
    const first = parseFrames('data: {"event":"sweep_started"}\n\ndata: {"event":"pre');
    expect(first.events.map((e) => e.event)).toEqual(["sweep_started"]);
    const second = parseFrames(first.rest + 'fix_started"}\n\ndata: not json\n\ndata: {"event":"sweep_finished"}\n\n');
    expect(second.events.map((e) => e.event)).toEqual(["prefix_started", "sweep_finished"]);
    expect(second.rest).toBe("");
  });
});
