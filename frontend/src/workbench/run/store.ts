import { create } from "zustand";

import {
  DEFAULT_DESIGN,
  PRESETS,
  designFromSpec,
  retainAvailable,
  type AxisKey,
  type SweepAxes,
  type SweepDesign,
  type SweepRequest,
} from "./design";
import { IDLE_RUN, STARTED_RUN, reduceRun, type RunState } from "./progress";
import { streamSweepRun } from "./stream";

// The design and the run belong to one campaign, and live here rather than in the panels:
// dockview unmounts a phase's panels when the phase changes, and a sweep started from Run
// keeps streaming while the analyst looks at Prepare.

interface DesignStore {
  design: SweepDesign;
  /** Levels a preset, the carried-over default or `setDesign` named that the campaign cannot
   * run; dropped rather than left ticked and disabled. */
  dropped: string[];
  /** The design has not yet met the campaign's axes (set by `setDesign`). */
  unchecked: boolean;
  toggle: (axis: AxisKey, level: string) => void;
  applyPreset: (name: string, axes: SweepAxes | null) => void;
  /** Intersect the design with the campaign's axes; called when the axes arrive or `setDesign` ran. */
  retain: (axes: SweepAxes) => void;
  setHubHeight: (value: number | null) => void;
  setAnalystShearAlpha: (value: number | null) => void;
  /** Replace the whole design from a request-shaped spec ("Sweep around this"). */
  setDesign: (spec: Partial<SweepRequest>) => void;
  reset: () => void;
}

export const useDesign = create<DesignStore>((set) => ({
  design: DEFAULT_DESIGN,
  dropped: [],
  unchecked: true,
  toggle: (axis, level) =>
    set((state) => {
      const current = state.design[axis];
      const next = current.includes(level) ? current.filter((entry) => entry !== level) : [...current, level];
      return { design: { ...state.design, [axis]: next } };
    }),
  applyPreset: (name, axes) =>
    set((state) => {
      const merged = { ...state.design, ...(PRESETS[name] ?? {}) };
      const { design, dropped } = retainAvailable(merged, axes);
      return { design, dropped, unchecked: axes === null };
    }),
  retain: (axes) =>
    set((state) => {
      const { design, dropped } = retainAvailable(state.design, axes);
      return { design, dropped: dropped.length > 0 ? dropped : state.dropped, unchecked: false };
    }),
  setHubHeight: (value) => set((state) => ({ design: { ...state.design, hub_height_m: value } })),
  setAnalystShearAlpha: (value) => set((state) => ({ design: { ...state.design, analyst_shear_alpha: value } })),
  setDesign: (spec) => set({ design: designFromSpec(spec), dropped: [], unchecked: true }),
  reset: () => set({ design: DEFAULT_DESIGN, dropped: [], unchecked: true }),
}));

interface RunStore {
  run: RunState;
  start: (sessionId: string, body: SweepRequest) => Promise<void>;
  /** Abandon a stream in flight (the campaign changed); the server keeps running its sweep. */
  reset: () => void;
}

let active: AbortController | null = null;

export const useRun = create<RunStore>((set, get) => ({
  run: IDLE_RUN,
  start: async (sessionId, body) => {
    if (get().run.phase === "running") return;
    active?.abort();
    const controller = new AbortController();
    active = controller;
    set({ run: STARTED_RUN });
    const apply = (event: Parameters<typeof reduceRun>[1]) => {
      if (controller.signal.aborted) return;
      set((state) => ({ run: reduceRun(state.run, event) }));
      if (event.event === "sweep_finished" && event.manifest?.sweep_id) {
        useLatestSweep.getState().record(sessionId, event.manifest.sweep_id);
      }
    };
    try {
      await streamSweepRun(sessionId, body, apply, controller.signal);
      if (!controller.signal.aborted && get().run.phase === "running") {
        set((state) => ({ run: { ...state.run, phase: "error", error: "The stream ended before the sweep finished" } }));
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      set((state) => ({
        run: { ...state.run, phase: "error", error: error instanceof Error ? error.message : String(error) },
      }));
    }
  },
  reset: () => {
    active?.abort();
    active = null;
    set({ run: IDLE_RUN });
  },
}));

interface LatestSweepStore {
  bySession: Record<string, string>;
  record: (sessionId: string, sweepId: string) => void;
}

/** The sweep id each campaign's last finished run produced; what Interrogate opens first. */
export const useLatestSweep = create<LatestSweepStore>((set) => ({
  bySession: {},
  record: (sessionId, sweepId) => set((state) => ({ bySession: { ...state.bySession, [sessionId]: sweepId } })),
}));

export function useLatestSweepId(sessionId: string): string | null {
  return useLatestSweep((state) => state.bySession[sessionId] ?? null);
}

export function resetRunPhase() {
  useDesign.getState().reset();
  useRun.getState().reset();
}
