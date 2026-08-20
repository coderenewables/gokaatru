// Scenario-sweep store (design doc §9.7).
//
// Deliberately separate from `useWorkspaceStore`, which is already ~2,000 lines. The
// sweep has its own lifecycle — design, run, explore — and nothing in the stage-based
// workspace needs to know about it.
import { create } from "zustand";

import {
  estimateSweep,
  getScenarioRunconfig,
  getSweep,
  getSweepAxes,
  listSweeps,
  streamSweep,
} from "../lib/sweepApi";
import { LTC_ALGORITHMS } from "../types/sweep";
import type {
  AxisColumn,
  ScenarioRow,
  SweepAxes,
  SweepManifest,
  SweepProgressEvent,
  SweepRequestBody,
  SweepSummary,
} from "../types/sweep";
import type { AxisFilters } from "../lib/sweepAnalysis";
import type { MetricColumn } from "../types/sweep";

/** What the designer holds while the analyst assembles a sweep. */
export interface SweepSelection {
  shearFitPolicies: string[];
  referencePolicies: string[];
  shearModels: string[];
  referenceSources: string[];
  ltcAlgorithms: string[];
  /** Required when a shear-fit policy resolves to fewer than two heights (§3.A.1). */
  analystShearAlpha: number | null;
  thresholds: Record<string, number>;
}

export type SweepPhase = "idle" | "running" | "complete" | "error";

const DEFAULT_SELECTION: SweepSelection = {
  shearFitPolicies: ["nearest_2"],
  referencePolicies: ["nearest_2"],
  shearModels: ["power_law_mean"],
  referenceSources: ["era5", "merra2"],
  ltcAlgorithms: ["variance_ratio", "linear_least_squares"],
  analystShearAlpha: null,
  thresholds: {},
};

/**
 * Presets carry different treatments of axis A (design doc §4).
 *
 * `Standard EYA` ties A1 = A2; `Exhaustive` crosses them fully. Crossing is always
 * available — it is simply not the default, because the leaf count is the binding
 * constraint on the whole engine.
 */
export const SWEEP_PRESETS: Record<string, Partial<SweepSelection>> = {
  "Quick look": {
    shearFitPolicies: ["nearest_2"],
    referencePolicies: ["nearest_2"],
    shearModels: ["power_law_mean"],
    referenceSources: ["era5"],
    ltcAlgorithms: ["variance_ratio"],
  },
  "Standard EYA": {
    shearFitPolicies: ["nearest_2", "widest_lever"],
    referencePolicies: ["nearest_2", "widest_lever"],
    shearModels: ["power_law_mean", "power_law_momm"],
    referenceSources: ["era5", "merra2"],
    ltcAlgorithms: ["variance_ratio", "linear_least_squares", "total_least_squares"],
  },
  Exhaustive: {
    shearFitPolicies: ["nearest_2", "availability_90", "redundant_boom", "widest_lever"],
    referencePolicies: ["nearest_2", "availability_90", "redundant_boom", "widest_lever"],
    shearModels: [
      "power_law_mean",
      "power_law_median",
      "power_law_momm",
      "power_law_constant",
      "log_law_mean",
    ],
    referenceSources: ["era5", "merra2"],
    ltcAlgorithms: [...LTC_ALGORITHMS],
  },
};

interface SweepStore {
  axes: SweepAxes | null;
  axesError: string | null;
  selection: SweepSelection;

  phase: SweepPhase;
  error: string | null;
  progress: { completed: number; total: number };
  events: SweepProgressEvent[];
  liveRows: ScenarioRow[];

  manifest: SweepManifest | null;
  rows: ScenarioRow[];
  sweeps: SweepSummary[];

  metric: MetricColumn;
  filters: AxisFilters;
  showInadmissible: boolean;
  selectedScenario: string | null;

  loadAxes: (baseUrl: string, sessionId: string) => Promise<void>;
  setSelection: (patch: Partial<SweepSelection>) => void;
  toggleLevel: (key: keyof SweepSelection, level: string) => void;
  applyPreset: (name: string) => void;
  estimate: (baseUrl: string, sessionId: string) => Promise<{ leaf_count: number; prefix_count: number } | null>;
  start: (baseUrl: string, sessionId: string) => Promise<void>;
  stop: () => void;
  refreshSweeps: (baseUrl: string, sessionId: string) => Promise<void>;
  openSweep: (baseUrl: string, sessionId: string, sweepId: string) => Promise<void>;
  downloadRunconfig: (baseUrl: string, sessionId: string, configHash: string) => Promise<void>;

  setMetric: (metric: MetricColumn) => void;
  setFilter: (axis: AxisColumn, levels: string[]) => void;
  clearFilters: () => void;
  setShowInadmissible: (value: boolean) => void;
  selectScenario: (configHash: string | null) => void;
  reset: () => void;
}

function toRequestBody(selection: SweepSelection): SweepRequestBody {
  return {
    shear_fit_policies: selection.shearFitPolicies,
    reference_policies: selection.referencePolicies,
    shear_models: selection.shearModels,
    reference_sources: selection.referenceSources,
    ltc_algorithms: selection.ltcAlgorithms,
    analyst_shear_alpha: selection.analystShearAlpha,
    thresholds: Object.keys(selection.thresholds).length > 0 ? selection.thresholds : null,
  };
}

/** Levels the selection names that this session cannot run — the designer greys these. */
export function unavailableSelections(
  selection: SweepSelection,
  axes: SweepAxes | null,
): string[] {
  if (!axes) return [];
  const unavailable = new Set(
    [...axes.sensor_policies, ...axes.shear_models, ...axes.reference_sources]
      .filter((level) => !level.available)
      .map((level) => level.name),
  );
  const chosen = [
    ...selection.shearFitPolicies,
    ...selection.referencePolicies,
    ...selection.shearModels,
    ...selection.referenceSources,
  ];
  return [...new Set(chosen.filter((name) => unavailable.has(name)))];
}

/**
 * Whether the sweep needs an analyst-supplied exponent before it can launch (§3.A.1).
 *
 * True when a chosen shear-fit policy resolves to fewer than two distinct heights. The
 * field has no default on purpose: a prefilled value tabbed past is exactly how an
 * assumption becomes invisible.
 */
export function requiresAnalystShear(selection: SweepSelection, axes: SweepAxes | null): boolean {
  if (!axes) return false;
  return selection.shearFitPolicies.some((name) => {
    const level = axes.sensor_policies.find((entry) => entry.name === name);
    return Boolean(level?.available) && level?.can_fit_shear === false;
  });
}

let activeController: AbortController | null = null;

export const useSweepStore = create<SweepStore>((set, get) => ({
  axes: null,
  axesError: null,
  selection: { ...DEFAULT_SELECTION },

  phase: "idle",
  error: null,
  progress: { completed: 0, total: 0 },
  events: [],
  liveRows: [],

  manifest: null,
  rows: [],
  sweeps: [],

  metric: "long_term_mean_speed_mps",
  filters: {},
  showInadmissible: false,
  selectedScenario: null,

  loadAxes: async (baseUrl, sessionId) => {
    try {
      set({ axes: await getSweepAxes(baseUrl, sessionId), axesError: null });
    } catch (error) {
      set({ axes: null, axesError: error instanceof Error ? error.message : String(error) });
    }
  },

  setSelection: (patch) => set((state) => ({ selection: { ...state.selection, ...patch } })),

  toggleLevel: (key, level) =>
    set((state) => {
      const current = state.selection[key];
      if (!Array.isArray(current)) return state;
      const next = current.includes(level)
        ? current.filter((entry) => entry !== level)
        : [...current, level];
      return { selection: { ...state.selection, [key]: next } };
    }),

  applyPreset: (name) =>
    set((state) => ({
      selection: { ...state.selection, ...(SWEEP_PRESETS[name] ?? {}) },
    })),

  estimate: async (baseUrl, sessionId) => {
    try {
      const result = await estimateSweep(baseUrl, sessionId, toRequestBody(get().selection));
      return { leaf_count: result.leaf_count, prefix_count: result.prefix_count };
    } catch {
      return null;
    }
  },

  start: async (baseUrl, sessionId) => {
    activeController?.abort();
    activeController = new AbortController();
    set({
      phase: "running",
      error: null,
      events: [],
      liveRows: [],
      progress: { completed: 0, total: 0 },
      manifest: null,
      rows: [],
      selectedScenario: null,
    });

    try {
      const manifest = await streamSweep(
        baseUrl,
        sessionId,
        toRequestBody(get().selection),
        (event) => {
          set((state) => ({
            events: [...state.events, event],
            progress: {
              completed: event.completed ?? state.progress.completed,
              total: event.total ?? state.progress.total,
            },
            error: event.event === "sweep_error" ? (event.error ?? "Sweep failed") : state.error,
          }));
        },
        activeController.signal,
      );
      if (manifest) {
        // The stream carries progress, not results; load the persisted table once.
        const outcome = await getSweep(baseUrl, sessionId, manifest.sweep_id);
        set({ manifest: outcome.manifest, rows: outcome.results, phase: "complete" });
        await get().refreshSweeps(baseUrl, sessionId);
      } else {
        set({ phase: get().error ? "error" : "complete" });
      }
    } catch (error) {
      if ((error as { name?: string }).name === "AbortError") {
        set({ phase: "idle" });
        return;
      }
      set({ phase: "error", error: error instanceof Error ? error.message : String(error) });
    } finally {
      activeController = null;
    }
  },

  stop: () => {
    activeController?.abort();
    activeController = null;
    set({ phase: "idle" });
  },

  refreshSweeps: async (baseUrl, sessionId) => {
    try {
      set({ sweeps: await listSweeps(baseUrl, sessionId) });
    } catch {
      set({ sweeps: [] });
    }
  },

  openSweep: async (baseUrl, sessionId, sweepId) => {
    try {
      const outcome = await getSweep(baseUrl, sessionId, sweepId);
      set({
        manifest: outcome.manifest,
        rows: outcome.results,
        phase: "complete",
        error: null,
        filters: {},
        selectedScenario: null,
      });
    } catch (error) {
      set({ phase: "error", error: error instanceof Error ? error.message : String(error) });
    }
  },

  downloadRunconfig: async (baseUrl, sessionId, configHash) => {
    const manifest = get().manifest;
    if (!manifest) return;
    const config = await getScenarioRunconfig(baseUrl, sessionId, manifest.sweep_id, configHash);
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `runconfig-${configHash}.json`;
    link.click();
    URL.revokeObjectURL(url);
  },

  setMetric: (metric) => set({ metric }),
  setFilter: (axis, levels) =>
    set((state) => ({ filters: { ...state.filters, [axis]: levels } })),
  clearFilters: () => set({ filters: {} }),
  setShowInadmissible: (value) => set({ showInadmissible: value }),
  selectScenario: (configHash) => set({ selectedScenario: configHash }),

  reset: () =>
    set({
      phase: "idle",
      error: null,
      events: [],
      liveRows: [],
      progress: { completed: 0, total: 0 },
      manifest: null,
      rows: [],
      filters: {},
      selectedScenario: null,
    }),
}));
